"""
Enrichment Chain — transforms raw evidence into telecom-aware intelligence.

Implements ABEYANCE_MEMORY_LLD.md §6 (The Enrichment Chain).

The 4-step pipeline runs at ingestion time, before the fragment is stored.
Each step adds a layer of domain knowledge that a generic vector database
cannot possess:
  Step 1: Entity Resolution (§6 Step 1)
  Step 2: Operational Fingerprinting (§6 Step 2)
  Step 3: Failure Mode Classification (§6 Step 3)
  Step 4: Temporal-Semantic Embedding (§6 Step 4 + §7)
"""

import math
import hashlib
import struct
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.core.logging import get_logger
from backend.app.models.abeyance_orm import AbeyanceFragmentORM, FragmentEntityRefORM
from backend.app.schemas.abeyance import (
    FailureModeTag,
    OperationalFingerprint,
    RawEvidence,
    SOURCE_TYPE_DEFAULTS,
    TemporalContext,
)
from backend.app.services.abeyance.shadow_topology import ShadowTopologyService

logger = get_logger(__name__)

# Entity extraction patterns for deterministic sources
_ENTITY_PATTERNS = {
    "ALARM": ["entity_id", "source_entity", "managed_object"],
    "TELEMETRY_EVENT": ["entity_id", "cell_id", "node_id"],
    "CHANGE_RECORD": ["affected_ci", "entity_id", "target_entity"],
    "CMDB_DELTA": ["entity_id", "ci_id"],
}


class EnrichmentChain:
    """The 4-step enrichment chain (LLD §6).

    Transforms raw evidence into telecom-aware intelligence by resolving
    entities through topology, fingerprinting operational context, classifying
    failure modes, and constructing temporal-semantic embeddings.
    """

    # Enriched embedding dimensions (LLD §6 Step 4)
    SEMANTIC_DIM = 512
    TOPOLOGICAL_DIM = 384
    TEMPORAL_DIM = 256
    OPERATIONAL_DIM = 384
    ENRICHED_DIM = SEMANTIC_DIM + TOPOLOGICAL_DIM + TEMPORAL_DIM + OPERATIONAL_DIM  # 1536

    def __init__(
        self,
        embedding_service: Any,
        shadow_topology: ShadowTopologyService,
        llm_service: Any = None,
        session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
    ):
        self.embedding_service = embedding_service
        self.shadow_topology = shadow_topology
        self.llm_service = llm_service
        self.session_factory = session_factory

    async def enrich(
        self,
        raw_evidence: RawEvidence,
        tenant_id: str,
        session: Optional[AsyncSession] = None,
    ) -> AbeyanceFragmentORM:
        """Execute the full 4-step enrichment pipeline (LLD §6).

        Returns a fully enriched AbeyanceFragmentORM ready for persistence.
        """
        now = datetime.now(timezone.utc)
        event_time = raw_evidence.event_timestamp or now

        # Step 1: Entity Resolution (LLD §6 Step 1)
        entity_refs = await self._resolve_entities(raw_evidence, tenant_id, session)
        entity_identifiers = [ref["entity_identifier"] for ref in entity_refs]

        # Step 1b: Topology Expansion via Shadow Topology
        neighbourhood = {}
        expanded_refs = []
        for ident in entity_identifiers:
            nbr = await self.shadow_topology.get_neighbourhood(
                tenant_id=tenant_id,
                entity_identifier=ident,
                hops=2,
                session=session,
            )
            for ent in nbr.entities:
                if ent.entity_identifier not in entity_identifiers:
                    # Compute hop distance (1 or 2)
                    distance = 1 if any(
                        r.from_entity_id == ent.id or r.to_entity_id == ent.id
                        for r in nbr.relationships[:20]
                    ) else 2
                    expanded_refs.append({
                        "entity_identifier": ent.entity_identifier,
                        "entity_domain": ent.entity_domain,
                        "topological_distance": distance,
                    })
            neighbourhood[ident] = {
                "entities": [e.entity_identifier for e in nbr.entities],
                "relationship_count": len(nbr.relationships),
            }

        all_entity_refs = entity_refs + expanded_refs

        # Step 2: Operational Fingerprinting (LLD §6 Step 2)
        fingerprint = await self._build_operational_fingerprint(
            entity_identifiers=entity_identifiers,
            event_time=event_time,
            tenant_id=tenant_id,
            session=session,
        )

        # Step 3: Failure Mode Classification (LLD §6 Step 3)
        failure_tags = self._classify_failure_modes(
            entity_refs=entity_refs,
            expanded_refs=expanded_refs,
            fingerprint=fingerprint,
            raw_content=raw_evidence.content,
        )

        # Step 4: Temporal-Semantic Embedding (LLD §6 Step 4 + §7)
        temporal_ctx = self._build_temporal_context(event_time, fingerprint)

        # Generate raw embedding from content
        raw_embedding = await self._generate_raw_embedding(raw_evidence.content)

        # Construct enriched embedding (1536-dim composite)
        enriched_embedding = self._construct_enriched_embedding(
            raw_embedding=raw_embedding,
            entity_refs=all_entity_refs,
            neighbourhood=neighbourhood,
            temporal_ctx=temporal_ctx,
            fingerprint=fingerprint,
            failure_tags=failure_tags,
        )

        # Determine base relevance from source type (LLD §5 table)
        defaults = SOURCE_TYPE_DEFAULTS.get(
            raw_evidence.source_type.value,
            {"base_relevance": 0.7, "decay_tau": 90.0},
        )

        # Build the fragment
        fragment = AbeyanceFragmentORM(
            id=uuid4(),
            tenant_id=tenant_id,
            source_type=raw_evidence.source_type.value,
            raw_content=raw_evidence.content,
            extracted_entities=[r for r in entity_refs],
            topological_neighbourhood=neighbourhood,
            operational_fingerprint=fingerprint.model_dump(),
            failure_mode_tags=[t.model_dump() for t in failure_tags],
            temporal_context=temporal_ctx.model_dump(),
            enriched_embedding=enriched_embedding,
            raw_embedding=raw_embedding,
            event_timestamp=event_time,
            base_relevance=defaults["base_relevance"],
            current_decay_score=defaults["base_relevance"],
            source_ref=raw_evidence.source_ref,
            source_engineer_id=raw_evidence.source_engineer_id,
        )

        # Create FragmentEntityRef records
        if session:
            session.add(fragment)
            for ref in all_entity_refs:
                entity_ref = FragmentEntityRefORM(
                    id=uuid4(),
                    fragment_id=fragment.id,
                    entity_identifier=ref["entity_identifier"],
                    entity_domain=ref.get("entity_domain"),
                    topological_distance=ref.get("topological_distance", 0),
                    tenant_id=tenant_id,
                )
                session.add(entity_ref)
            await session.flush()

        logger.info(
            f"Fragment enriched: id={fragment.id}, "
            f"entities={len(all_entity_refs)}, "
            f"failure_modes={len(failure_tags)}, "
            f"source_type={raw_evidence.source_type.value}"
        )
        return fragment

    async def _resolve_entities(
        self,
        evidence: RawEvidence,
        tenant_id: str,
        session: Optional[AsyncSession] = None,
    ) -> list[dict]:
        """Step 1: Entity Resolution (LLD §6 Step 1).

        For structured sources (alarms, telemetry), extracts entities
        deterministically from payload. For text sources, uses LLM
        extraction or regex fallback.
        """
        entities = []

        # Explicit entity refs from the evidence payload
        for ref in evidence.entity_refs:
            entities.append({
                "entity_identifier": ref,
                "entity_domain": None,
                "topological_distance": 0,
            })

        # For structured sources, parse metadata
        source = evidence.source_type.value
        if source in _ENTITY_PATTERNS:
            for key in _ENTITY_PATTERNS[source]:
                val = evidence.metadata.get(key)
                if val and str(val) not in [e["entity_identifier"] for e in entities]:
                    entities.append({
                        "entity_identifier": str(val),
                        "entity_domain": evidence.metadata.get("domain"),
                        "topological_distance": 0,
                    })

        # For text sources, try LLM extraction then regex fallback
        if source in ("TICKET_TEXT", "CLI_OUTPUT") and not entities:
            if self.llm_service:
                try:
                    extracted = await self._llm_extract_entities(evidence.content)
                    entities.extend(extracted)
                except Exception as e:
                    logger.warning(f"LLM entity extraction failed, using regex: {e}")
                    entities.extend(self._regex_extract_entities(evidence.content))
            else:
                entities.extend(self._regex_extract_entities(evidence.content))

        return entities

    async def _llm_extract_entities(self, content: str) -> list[dict]:
        """Extract entities from unstructured text using LLM (LLD §6 Step 1)."""
        prompt = (
            "Given this NOC ticket resolution note, extract all network entity references:\n"
            "- Cell IDs (e.g., LTE-8842-A, NR-8842-A)\n"
            "- Site IDs (e.g., SITE-NW-1847)\n"
            "- IP addresses and subnets\n"
            "- Interface identifiers\n"
            "- Equipment identifiers (eNodeB, gNodeB, router names)\n"
            "- Error codes and alarm identifiers\n"
            "Return as a JSON array of {entity_identifier, entity_domain}.\n\n"
            f"Text: {content[:2000]}"
        )
        # Placeholder — actual LLM call would go through llm_service
        return self._regex_extract_entities(content)

    def _regex_extract_entities(self, content: str) -> list[dict]:
        """Fallback regex-based entity extraction for text content."""
        import re
        entities = []
        # Cell IDs: LTE-XXXX-X, NR-XXXX-X
        for m in re.finditer(r'\b((?:LTE|NR|5G)-\w+-\w+)\b', content, re.IGNORECASE):
            entities.append({"entity_identifier": m.group(1).upper(), "entity_domain": "RAN", "topological_distance": 0})
        # Site IDs: SITE-XX-XXXX
        for m in re.finditer(r'\b(SITE-\w+-\w+)\b', content, re.IGNORECASE):
            entities.append({"entity_identifier": m.group(1).upper(), "entity_domain": "SITE", "topological_distance": 0})
        # IP addresses
        for m in re.finditer(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:/\d{1,2})?)\b', content):
            entities.append({"entity_identifier": m.group(1), "entity_domain": "IP", "topological_distance": 0})
        # eNodeB / gNodeB
        for m in re.finditer(r'\b((?:ENB|GNB|eNodeB|gNodeB)-?\w+)\b', content, re.IGNORECASE):
            entities.append({"entity_identifier": m.group(1).upper(), "entity_domain": "RAN", "topological_distance": 0})
        # Transport nodes
        for m in re.finditer(r'\b(TN-\w+-\w+)\b', content, re.IGNORECASE):
            entities.append({"entity_identifier": m.group(1).upper(), "entity_domain": "TRANSPORT", "topological_distance": 0})
        # VLANs
        for m in re.finditer(r'\b(VLAN-?\d+)\b', content, re.IGNORECASE):
            entities.append({"entity_identifier": m.group(1).upper(), "entity_domain": "IP", "topological_distance": 0})

        # Deduplicate
        seen = set()
        unique = []
        for e in entities:
            key = e["entity_identifier"]
            if key not in seen:
                seen.add(key)
                unique.append(e)
        return unique

    async def _build_operational_fingerprint(
        self,
        entity_identifiers: list[str],
        event_time: datetime,
        tenant_id: str,
        session: Optional[AsyncSession] = None,
    ) -> OperationalFingerprint:
        """Step 2: Operational Fingerprinting (LLD §6 Step 2).

        Characterises the operational moment: change window proximity,
        vendor upgrade recency, traffic cycle position, concurrent alarms,
        and open incidents.
        """
        # For MVP, construct fingerprint from available context.
        # Full integration with ITSM, change records, and KPI store
        # will be wired in Phase 2 (LLD §16).
        fingerprint = OperationalFingerprint(
            change_proximity={
                "nearest_change_hours": None,
                "change_ticket_id": None,
                "change_type": None,
            },
            vendor_upgrade={
                "days_since_upgrade": None,
                "vendor": None,
            },
            traffic_cycle={
                "time_bucket": _time_bucket(event_time),
                "hour_utc": event_time.hour,
                "day_of_week": event_time.strftime("%A"),
                "load_ratio_vs_baseline": 0.5,  # default neutral
            },
            concurrent_alarms={
                "count_1h_window": 0,
                "dominant_types": [],
            },
            open_incidents=[],
        )
        return fingerprint

    def _classify_failure_modes(
        self,
        entity_refs: list[dict],
        expanded_refs: list[dict],
        fingerprint: OperationalFingerprint,
        raw_content: str,
    ) -> list[FailureModeTag]:
        """Step 3: Failure Mode Classification (LLD §6 Step 3).

        Rule-based heuristics against the Dark Graph divergence taxonomy.
        Returns multiple tags with confidence scores.
        """
        tags = []
        content_lower = raw_content.lower()

        # DARK_EDGE: entities from different domains co-referenced
        domains = set(r.get("entity_domain") for r in entity_refs if r.get("entity_domain"))
        if len(domains) > 1:
            tags.append(FailureModeTag(
                divergence_type="DARK_EDGE",
                confidence=0.5 + 0.1 * len(domains),
                rationale=f"Cross-domain entity references: {', '.join(domains)}",
                candidate_entities=[r["entity_identifier"] for r in entity_refs],
            ))

        # DARK_NODE: mentions of unknown/unregistered entities
        if any(kw in content_lower for kw in ["unknown", "unregistered", "not found in cmdb", "not in inventory"]):
            tags.append(FailureModeTag(
                divergence_type="DARK_NODE",
                confidence=0.7,
                rationale="Content references unknown or unregistered entities",
                candidate_entities=[r["entity_identifier"] for r in entity_refs[:3]],
            ))

        # PHANTOM_NODE: zero-telemetry / no activity indicators
        if any(kw in content_lower for kw in ["zero user", "no traffic", "inactive", "decommissioned", "phantom"]):
            tags.append(FailureModeTag(
                divergence_type="PHANTOM_NODE",
                confidence=0.6,
                rationale="Evidence of entity with zero operational footprint",
                candidate_entities=[r["entity_identifier"] for r in entity_refs[:3]],
            ))

        # IDENTITY_MUTATION: serial/MAC/model mismatch
        if any(kw in content_lower for kw in ["serial mismatch", "mac mismatch", "model changed", "hardware swap", "identity"]):
            tags.append(FailureModeTag(
                divergence_type="IDENTITY_MUTATION",
                confidence=0.7,
                rationale="Indicators of entity identity change",
                candidate_entities=[r["entity_identifier"] for r in entity_refs[:3]],
            ))

        # DARK_ATTRIBUTE: post-change parameter drift
        change_hours = fingerprint.change_proximity.get("nearest_change_hours")
        if change_hours is not None and change_hours < 72:
            if any(kw in content_lower for kw in ["parameter", "config", "degraded", "drift", "mismatch"]):
                tags.append(FailureModeTag(
                    divergence_type="DARK_ATTRIBUTE",
                    confidence=0.5,
                    rationale=f"Possible post-change parameter drift ({change_hours}h from change)",
                    candidate_entities=[r["entity_identifier"] for r in entity_refs[:3]],
                ))

        # Default: if no specific failure mode detected, tag as general
        if not tags:
            tags.append(FailureModeTag(
                divergence_type="DARK_EDGE",
                confidence=0.2,
                rationale="General fragment — no specific failure mode detected",
                candidate_entities=[r["entity_identifier"] for r in entity_refs[:3]],
            ))

        return tags

    def _build_temporal_context(
        self,
        event_time: datetime,
        fingerprint: OperationalFingerprint,
    ) -> TemporalContext:
        """Construct the temporal context vector (LLD §7).

        Uses sinusoidal encoding for cyclical time dimensions and
        Gaussian/exponential for operational time features.
        """
        hour = event_time.hour + event_time.minute / 60.0
        dow = event_time.weekday()
        doy = event_time.timetuple().tm_yday

        return TemporalContext(
            norm_timestamp=self._normalise_timestamp(event_time),
            time_of_day_sin=math.sin(2 * math.pi * hour / 24),
            time_of_day_cos=math.cos(2 * math.pi * hour / 24),
            day_of_week_sin=math.sin(2 * math.pi * dow / 7),
            day_of_week_cos=math.cos(2 * math.pi * dow / 7),
            change_proximity=fingerprint.change_proximity_gaussian,
            vendor_upgrade_recency=fingerprint.vendor_upgrade_decay,
            traffic_load_ratio=fingerprint.traffic_load_ratio,
            seasonal_sin=math.sin(2 * math.pi * doy / 365),
            seasonal_cos=math.cos(2 * math.pi * doy / 365),
        )

    def _normalise_timestamp(self, dt: datetime) -> float:
        """Normalise timestamp to 0-1 scale over a 2-year deployment range."""
        epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)
        deployment_range_days = 730.0  # 2 years
        delta = (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt) - epoch
        return max(0.0, min(1.0, delta.total_seconds() / (deployment_range_days * 86400)))

    async def _generate_raw_embedding(self, content: str) -> Optional[list[float]]:
        """Generate raw embedding from content text."""
        if self.embedding_service:
            try:
                emb = await self.embedding_service.generate_embedding(content)
                if emb:
                    # Truncate or pad to 768 dims for raw embedding
                    if len(emb) > 768:
                        return emb[:768]
                    elif len(emb) < 768:
                        return emb + [0.0] * (768 - len(emb))
                    return emb
            except Exception as e:
                logger.warning(f"Embedding generation failed: {e}")

        # Hash-based fallback (deterministic, for testing)
        return self._hash_embedding(content, 768)

    def _construct_enriched_embedding(
        self,
        raw_embedding: Optional[list[float]],
        entity_refs: list[dict],
        neighbourhood: dict,
        temporal_ctx: TemporalContext,
        fingerprint: OperationalFingerprint,
        failure_tags: list[FailureModeTag],
    ) -> list[float]:
        """Construct the 1536-dim enriched embedding (LLD §6 Step 4).

        Concatenates 4 sub-vectors:
        - Semantic (512-dim): from raw embedding
        - Topological (384-dim): from entity neighbourhood
        - Temporal (256-dim): from temporal context
        - Operational (384-dim): from fingerprint + failure modes
        """
        # Semantic sub-vector (512-dim) — truncated/projected from raw
        semantic = self._project_embedding(raw_embedding or [], self.SEMANTIC_DIM)

        # Topological sub-vector (384-dim) — hash-encoded from entity graph
        topo_text = " ".join(
            f"{r['entity_identifier']}:{r.get('entity_domain', 'UNK')}:{r.get('topological_distance', 0)}"
            for r in entity_refs
        )
        topological = self._hash_embedding(topo_text, self.TOPOLOGICAL_DIM)

        # Temporal sub-vector (256-dim) — direct numerical encoding
        temporal = self._build_temporal_vector(temporal_ctx)

        # Operational sub-vector (384-dim) — hash from fingerprint + failure modes
        oper_text = (
            f"change_proximity:{fingerprint.change_proximity_gaussian:.3f} "
            f"upgrade_recency:{fingerprint.vendor_upgrade_decay:.3f} "
            f"traffic:{fingerprint.traffic_load_ratio:.3f} "
            + " ".join(f"{t.divergence_type}:{t.confidence:.2f}" for t in failure_tags)
        )
        operational = self._hash_embedding(oper_text, self.OPERATIONAL_DIM)

        # Concatenate and L2-normalise (LLD §6 Step 4)
        enriched = semantic + topological + temporal + operational
        norm = math.sqrt(sum(x * x for x in enriched)) or 1.0
        return [x / norm for x in enriched]

    def _project_embedding(self, embedding: list[float], target_dim: int) -> list[float]:
        """Project/truncate embedding to target dimension."""
        if len(embedding) >= target_dim:
            return embedding[:target_dim]
        return embedding + [0.0] * (target_dim - len(embedding))

    def _build_temporal_vector(self, ctx: TemporalContext) -> list[float]:
        """Build the 256-dim temporal sub-vector (LLD §7).

        First 10 dimensions are the explicit temporal features.
        Remaining dimensions are zero-padded (reserved for per-customer
        temporal features per §7).
        """
        explicit = [
            ctx.norm_timestamp,
            ctx.time_of_day_sin,
            ctx.time_of_day_cos,
            ctx.day_of_week_sin,
            ctx.day_of_week_cos,
            ctx.change_proximity,
            ctx.vendor_upgrade_recency,
            ctx.traffic_load_ratio,
            ctx.seasonal_sin,
            ctx.seasonal_cos,
        ]
        return explicit + [0.0] * (self.TEMPORAL_DIM - len(explicit))

    def _hash_embedding(self, text: str, dim: int) -> list[float]:
        """Deterministic hash-based embedding for testing/fallback.

        Uses SHA256 to seed a reproducible random vector.
        """
        seed_bytes = hashlib.sha256(text.encode("utf-8")).digest()
        seed = struct.unpack("<I", seed_bytes[:4])[0]
        rng = np.random.RandomState(seed)
        vec = rng.randn(dim).astype(np.float32)
        norm = np.linalg.norm(vec) or 1.0
        return (vec / norm).tolist()


def _time_bucket(dt: datetime) -> str:
    """Classify time into operational buckets."""
    hour = dt.hour
    if 0 <= hour < 6:
        return "off_peak"
    elif 6 <= hour < 9:
        return "shoulder"
    elif 9 <= hour < 17:
        return "peak"
    elif 17 <= hour < 21:
        return "shoulder"
    else:
        return "off_peak"
