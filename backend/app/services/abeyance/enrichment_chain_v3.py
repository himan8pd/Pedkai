"""
Enrichment Chain v3.0 — T-VEC semantic/topological/operational, sinusoidal temporal.

LLD v3.0 §2.8: Four independent sub-embeddings (512/384/256/384) via T-VEC.
Entity extraction via TSLAM with regex fallback.
Zero cloud LLM dependency.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    FragmentEntityRefORM,
    MAX_RAW_CONTENT_BYTES,
)
from backend.app.services.abeyance.events import (
    FragmentStateChange,
    ProvenanceLogger,
)

logger = logging.getLogger(__name__)

# Embedding dimensions (LLD v3.0 §2.5)
SEMANTIC_DIM = 1536
TOPOLOGICAL_DIM = 1536
TEMPORAL_DIM = 256
OPERATIONAL_DIM = 1536

# Source-type defaults (LLD §5)
SOURCE_TYPE_DEFAULTS: dict[str, dict[str, float]] = {
    "TICKET_TEXT": {"base_relevance": 0.9, "decay_tau": 270.0},
    "ALARM": {"base_relevance": 0.7, "decay_tau": 90.0},
    "TELEMETRY_EVENT": {"base_relevance": 0.6, "decay_tau": 60.0},
    "CLI_OUTPUT": {"base_relevance": 0.7, "decay_tau": 180.0},
    "CHANGE_RECORD": {"base_relevance": 0.8, "decay_tau": 365.0},
    "CMDB_DELTA": {"base_relevance": 0.7, "decay_tau": 90.0},
}

# Entity extraction patterns
ENTITY_PATTERNS = [
    (r"(?:LTE|NR|GSM|UMTS)-\w+-[A-Z0-9]+", "RAN"),
    (r"SITE-[A-Z]+-\d+", "SITE"),
    (r"ENB-\d+", "RAN"),
    (r"GNB-\d+", "RAN"),
    (r"TN-[A-Z]+-\d+", "TRANSPORT"),
    (r"S1-\d+-\d+", "TRANSPORT"),
    (r"VLAN-\d+", "IP"),
    (r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:/\d{1,2})?", "IP"),
    (r"CR-[A-Z]+-\d+", "CORE"),
    (r"VNF-[A-Z0-9-]+", "VNF"),
    (r"CHG-\d{4}-[A-Z]+-\d+", None),
]


class EnrichmentChainV3:
    """v3 enrichment chain: T-VEC embeddings, TSLAM entities, sinusoidal temporal."""

    def __init__(
        self,
        provenance: ProvenanceLogger,
        tvec_service: Optional[Any] = None,
        tslam_service: Optional[Any] = None,
        shadow_topology: Optional[Any] = None,
        llm_service: Optional[Any] = None,
    ):
        self._provenance = provenance
        self._tvec = tvec_service
        self._tslam = tslam_service
        self._shadow_topology = shadow_topology
        self._llm = llm_service  # Backward compat: falls back to LLM if T-VEC not available

    async def enrich(
        self,
        session: AsyncSession,
        tenant_id: str,
        raw_content: str,
        source_type: str,
        event_timestamp: Optional[datetime] = None,
        source_ref: Optional[str] = None,
        source_engineer_id: Optional[str] = None,
        explicit_entity_refs: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
    ) -> AbeyanceFragmentORM:
        """Run full v3 enrichment chain and persist fragment."""
        # INV-6: raw content size bound
        if len(raw_content.encode("utf-8")) > MAX_RAW_CONTENT_BYTES:
            raw_content = raw_content[:MAX_RAW_CONTENT_BYTES // 4]
            logger.warning("Raw content truncated (INV-6)")

        now = datetime.now(timezone.utc)
        event_ts = event_timestamp or now

        # Step 1: Entity Resolution (TSLAM + regex)
        entities = await self._resolve_entities(raw_content, source_type, explicit_entity_refs)

        # Step 1.5: Topology expansion
        neighbourhood = {}
        if self._shadow_topology and entities:
            try:
                entity_ids = [e["identifier"] for e in entities]
                neighbourhood = await self._shadow_topology.get_neighbourhood(
                    session, tenant_id, entity_ids=entity_ids, max_hops=2,
                )
            except Exception:
                logger.warning("Shadow topology expansion failed", exc_info=True)

        # Step 2: Operational Fingerprinting
        fingerprint = await self._build_operational_fingerprint(entities, event_ts, tenant_id, session)

        # Step 3: Failure Mode Classification
        failure_modes = self._classify_failure_modes(entities, fingerprint, raw_content)

        # Step 4: Four-column embedding (T-VEC per-dimension)
        emb_result = await self._compute_v3_embeddings(
            raw_content, entities, neighbourhood, fingerprint, failure_modes, event_ts,
        )

        # Step 4.5: Polarity detection (for conflict detection, Mechanism #6)
        polarity = self._detect_polarity(raw_content)

        # Deduplication key
        dedup_key = self._compute_dedup_key(tenant_id, source_type, source_ref, event_ts)

        # Determine base relevance
        defaults = SOURCE_TYPE_DEFAULTS.get(source_type, {"base_relevance": 0.7})
        base_relevance = defaults["base_relevance"]

        # Temporal context (for legacy and temporal embedding reference)
        temporal_context = self._build_temporal_context(event_ts, fingerprint)

        # Build dual-write legacy embedding for v2 compat
        legacy_enriched, legacy_raw, legacy_mask = await self._compute_legacy_embeddings(
            raw_content, entities, neighbourhood, fingerprint, failure_modes, temporal_context,
        )

        # Create fragment
        fragment = AbeyanceFragmentORM(
            id=uuid4(),
            tenant_id=tenant_id,
            source_type=source_type,
            source_ref=source_ref,
            source_engineer_id=source_engineer_id,
            raw_content=raw_content,
            extracted_entities=[e for e in entities],
            topological_neighbourhood=neighbourhood,
            operational_fingerprint=fingerprint,
            failure_mode_tags=failure_modes,
            temporal_context=temporal_context,
            # v3 four-column embeddings
            emb_semantic=emb_result["semantic"]["vector"],
            emb_topological=emb_result["topological"]["vector"],
            emb_temporal=emb_result["temporal"]["vector"],
            emb_operational=emb_result["operational"]["vector"],
            mask_semantic=emb_result["semantic"]["valid"],
            mask_topological=emb_result["topological"]["valid"],
            mask_operational=emb_result["operational"]["valid"],
            polarity=polarity,
            embedding_schema_version=3,
            # Legacy dual-write
            embedding_mask=legacy_mask,
            enriched_embedding=legacy_enriched,
            raw_embedding=legacy_raw,
            # Timestamps
            event_timestamp=event_ts,
            base_relevance=base_relevance,
            current_decay_score=base_relevance,
            snap_status="ACTIVE",
            dedup_key=dedup_key,
        )
        session.add(fragment)

        # Entity refs
        for entity in entities:
            ref = FragmentEntityRefORM(
                id=uuid4(),
                fragment_id=fragment.id,
                entity_identifier=entity["identifier"],
                entity_domain=entity.get("domain"),
                topological_distance=entity.get("distance", 0),
                tenant_id=tenant_id,
            )
            session.add(ref)

        # Provenance
        await self._provenance.log_state_change(
            session,
            FragmentStateChange(
                fragment_id=fragment.id,
                tenant_id=tenant_id,
                event_type="CREATED",
                new_state={
                    "status": "ACTIVE",
                    "base_relevance": base_relevance,
                    "entity_count": len(entities),
                    "embedding_schema_version": 3,
                    "mask_semantic": emb_result["semantic"]["valid"],
                    "mask_topological": emb_result["topological"]["valid"],
                    "mask_operational": emb_result["operational"]["valid"],
                    "polarity": polarity,
                },
            ),
        )

        await session.flush()
        return fragment

    # --- Step 1: Entity Resolution ---

    async def _resolve_entities(
        self, content: str, source_type: str, explicit_refs: Optional[list[str]] = None,
    ) -> list[dict]:
        entities = []

        # TSLAM extraction (replaces cloud LLM)
        if self._tslam and source_type in ("TICKET_TEXT", "CLI_OUTPUT"):
            try:
                llm_entities = await self._tslam_extract_entities(content)
                entities.extend(llm_entities)
            except Exception:
                logger.warning("TSLAM entity extraction failed, using regex", exc_info=True)

        # Fallback: LLM service (backward compat)
        if not entities and self._llm and source_type in ("TICKET_TEXT", "CLI_OUTPUT"):
            try:
                llm_entities = await self._llm_extract_entities(content)
                entities.extend(llm_entities)
            except Exception:
                logger.warning("LLM entity extraction failed", exc_info=True)

        # Regex (always runs)
        regex_entities = self._regex_extract_entities(content)
        seen = {e["identifier"] for e in entities}
        for re_ent in regex_entities:
            if re_ent["identifier"] not in seen:
                entities.append(re_ent)
                seen.add(re_ent["identifier"])

        if explicit_refs:
            for ref in explicit_refs:
                if ref not in seen:
                    entities.append({"identifier": ref, "domain": None, "distance": 0})
                    seen.add(ref)

        return entities

    async def _tslam_extract_entities(self, content: str) -> list[dict]:
        if not self._tslam:
            return []
        schema = {
            "entities": [{"identifier": "string", "domain": "string"}]
        }
        result = await self._tslam.generate_structured(
            f"Extract all network entity references from this NOC text:\n{content[:2000]}",
            schema=schema,
        )
        if result and "entities" in result:
            return [
                {"identifier": e.get("identifier", ""), "domain": e.get("domain"), "distance": 0}
                for e in result["entities"]
                if isinstance(e, dict) and e.get("identifier")
            ]
        return []

    async def _llm_extract_entities(self, content: str) -> list[dict]:
        if not self._llm:
            return []
        import json
        prompt = (
            "Extract all network entity references from this NOC text. "
            "Return a JSON array of objects with 'identifier' and 'domain'.\n\n"
            f"Text: {content[:2000]}"
        )
        try:
            response = await self._llm.generate(prompt, max_tokens=500)
            entities = json.loads(response)
            if isinstance(entities, list):
                return [
                    {"identifier": e.get("identifier", ""), "domain": e.get("domain"), "distance": 0}
                    for e in entities if isinstance(e, dict) and e.get("identifier")
                ]
        except Exception:
            pass
        return []

    def _regex_extract_entities(self, content: str) -> list[dict]:
        entities, seen = [], set()
        for pattern, domain in ENTITY_PATTERNS:
            for match in re.finditer(pattern, content):
                identifier = match.group(0)
                if identifier not in seen:
                    entities.append({"identifier": identifier, "domain": domain, "distance": 0})
                    seen.add(identifier)
        return entities

    # --- Step 2: Operational Fingerprinting ---

    async def _build_operational_fingerprint(
        self, entities: list[dict], event_time: datetime, tenant_id: str, session: AsyncSession,
    ) -> dict:
        return {
            "change_proximity": {"nearest_change_hours": None},
            "vendor_upgrade": {"days_since_upgrade": None},
            "traffic_cycle": {
                "load_ratio_vs_baseline": None,
                "time_bucket": self._time_bucket(event_time),
                "hour_utc": event_time.hour,
                "day_of_week": event_time.strftime("%A"),
            },
            "concurrent_alarms": {"count_1h_window": None},
            "open_incidents": [],
        }

    @staticmethod
    def _time_bucket(dt: datetime) -> str:
        hour = dt.hour
        if 6 <= hour < 9 or 17 <= hour < 21:
            return "shoulder"
        elif 9 <= hour < 17:
            return "peak"
        return "off_peak"

    # --- Step 3: Failure Mode Classification ---

    def _classify_failure_modes(self, entities: list[dict], fingerprint: dict, content: str) -> list[dict]:
        tags = []
        content_lower = content.lower()
        if len(entities) >= 2:
            domains = {e.get("domain") for e in entities if e.get("domain")}
            if len(domains) >= 2:
                tags.append({"divergence_type": "DARK_EDGE", "confidence": 0.5,
                             "rationale": f"Cross-domain ({', '.join(domains)})",
                             "candidate_entities": [e["identifier"] for e in entities[:4]]})
        kw_map = {
            "DARK_NODE": ["unknown", "unregistered", "not in cmdb", "not found in inventory"],
            "IDENTITY_MUTATION": ["serial mismatch", "wrong model", "replaced", "swapped"],
            "PHANTOM_CI": ["no traffic", "zero users", "no telemetry", "decommissioned"],
            "DARK_ATTRIBUTE": ["parameter mismatch", "config drift", "unexpected frequency"],
        }
        for mode, keywords in kw_map.items():
            if any(kw in content_lower for kw in keywords):
                tags.append({"divergence_type": mode, "confidence": 0.5,
                             "rationale": f"{mode} keyword detected",
                             "candidate_entities": [e["identifier"] for e in entities[:2]]})
        return tags

    # --- Step 4: v3 Four-Column Embeddings ---

    async def _compute_v3_embeddings(
        self,
        raw_content: str,
        entities: list[dict],
        neighbourhood: dict,
        fingerprint: dict,
        failure_modes: list[dict],
        event_time: datetime,
    ) -> dict:
        result = {
            "semantic": {"vector": None, "valid": False},
            "topological": {"vector": None, "valid": False},
            "temporal": {"vector": None, "valid": True},
            "operational": {"vector": None, "valid": False},
        }

        embed_fn = self._tvec.embed if self._tvec else (self._llm.embed if self._llm and hasattr(self._llm, "embed") else None)

        # Prepare texts for embedding
        semantic_text = None
        topo_text = None
        oper_text = None
        if embed_fn:
            entity_text = ", ".join(e["identifier"] for e in entities[:20])
            semantic_text = f"{raw_content[:1000]} Entities: {entity_text}"
            if entities:
                topo_text = self._build_topo_text(entities, neighbourhood)
            if failure_modes:
                oper_text = self._build_operational_text(failure_modes, fingerprint)

        # Run embedding calls concurrently (micro-batch if possible)
        semantic_vec, topo_vec, oper_vec = None, None, None
        if embed_fn:
            tasks = []
            texts = []
            if semantic_text:
                texts.append(semantic_text)
            if topo_text:
                texts.append(topo_text)
            if oper_text:
                texts.append(oper_text)
            # Use batch embedding if available
            if hasattr(self._tvec, "embed_batch") and len(texts) > 1:
                try:
                    batch_vecs = await self._tvec.embed_batch(texts)
                    idx = 0
                    if semantic_text:
                        semantic_vec = batch_vecs[idx]
                        idx += 1
                    if topo_text:
                        topo_vec = batch_vecs[idx] if idx < len(batch_vecs) else None
                        idx += 1
                    if oper_text:
                        oper_vec = batch_vecs[idx] if idx < len(batch_vecs) else None
                except Exception:
                    logger.warning("T-VEC batch embedding failed", exc_info=True)
            else:
                # Fallback: run concurrently
                async def safe_embed(text):
                    try:
                        return await embed_fn(text)
                    except Exception:
                        logger.warning("Embedding failed for text", exc_info=True)
                        return None
                coros = []
                if semantic_text:
                    coros.append(safe_embed(semantic_text))
                if topo_text:
                    coros.append(safe_embed(topo_text))
                if oper_text:
                    coros.append(safe_embed(oper_text))
                results = await asyncio.gather(*coros)
                idx = 0
                if semantic_text:
                    semantic_vec = results[idx]
                    idx += 1
                if topo_text:
                    topo_vec = results[idx] if idx < len(results) else None
                    idx += 1
                if oper_text:
                    oper_vec = results[idx] if idx < len(results) else None

        # Assign results — INV-12: reject all-zero vectors as invalid
        for col, vec, dim in [
            ("semantic", semantic_vec, SEMANTIC_DIM),
            ("topological", topo_vec, TOPOLOGICAL_DIM),
            ("operational", oper_vec, OPERATIONAL_DIM),
        ]:
            if vec is not None:
                padded = self._pad_or_trim(vec, dim)
                if self._is_zero_vector(padded):
                    logger.warning(
                        "INV-12 violation: %s embedding is all-zero, marking invalid", col,
                    )
                    result[col]["vector"] = None
                    result[col]["valid"] = False
                else:
                    result[col]["vector"] = padded
                    result[col]["valid"] = True
            else:
                result[col]["vector"] = None
                result[col]["valid"] = False

        # Temporal (sinusoidal encoding — always valid, no model needed)
        result["temporal"]["vector"] = self._build_temporal_vector(event_time, fingerprint)

        return result

    @staticmethod
    def _pad_or_trim(vec: list[float], target_dim: int) -> list[float]:
        if len(vec) < target_dim:
            return vec + [0.0] * (target_dim - len(vec))
        return vec[:target_dim]

    @staticmethod
    def _is_zero_vector(vec: list[float]) -> bool:
        """INV-12: detect all-zero embeddings that would poison similarity calculations."""
        return all(v == 0.0 for v in vec)

    def _build_topo_text(self, entities: list[dict], neighbourhood: dict) -> str:
        parts = [f"{e['identifier']} ({e.get('domain', 'unknown')})" for e in entities[:20]]
        return f"Network topology context: {', '.join(parts)}"

    def _build_operational_text(self, failure_modes: list[dict], fingerprint: dict) -> str:
        parts = []
        for fm in failure_modes[:5]:
            if isinstance(fm, dict):
                parts.append(f"{fm.get('divergence_type', 'unknown')}: {fm.get('rationale', '')}")
        time_bucket = (fingerprint.get("traffic_cycle") or {}).get("time_bucket", "unknown")
        parts.append(f"Traffic: {time_bucket}")
        return f"Operational context: {'; '.join(parts)}"

    def _build_temporal_vector(self, event_time: datetime, fingerprint: dict) -> list[float]:
        """Build 256-dim deterministic sinusoidal temporal vector as per LLD."""
        # Deterministic encoding: fill all 256 dims with sin/cos harmonics of time features
        hour = event_time.hour + event_time.minute / 60.0
        dow = event_time.weekday()
        doy = event_time.timetuple().tm_yday

        change_hours = (fingerprint.get("change_proximity") or {}).get("nearest_change_hours")
        change_prox = math.exp(-(change_hours ** 2) / (2 * 24 ** 2)) if change_hours is not None else 0.0
        upgrade_days = (fingerprint.get("vendor_upgrade") or {}).get("days_since_upgrade")
        upgrade_decay = math.exp(-upgrade_days / 30.0) if upgrade_days is not None else 0.0
        load_ratio = (fingerprint.get("traffic_cycle") or {}).get("load_ratio_vs_baseline") or 0.0

        # Fill 256 dims with harmonics of hour, dow, doy, and other features
        vec = [0.0] * TEMPORAL_DIM
        for i in range(TEMPORAL_DIM):
            # Use different frequencies for each feature
            freq = 1 + (i % 32)
            if i < 64:
                # Hour of day
                vec[i] = math.sin(2 * math.pi * freq * hour / 24)
            elif i < 128:
                # Day of week
                vec[i] = math.cos(2 * math.pi * freq * dow / 7)
            elif i < 192:
                # Day of year
                vec[i] = math.sin(2 * math.pi * freq * doy / 365)
            else:
                # Remaining: encode change proximity, upgrade decay, load ratio
                if i % 3 == 0:
                    vec[i] = change_prox
                elif i % 3 == 1:
                    vec[i] = upgrade_decay
                else:
                    vec[i] = load_ratio
        return vec

    def _build_temporal_context(self, event_time: datetime, fingerprint: dict) -> dict:
        """Legacy temporal context dict for backward compat."""
        hour = event_time.hour + event_time.minute / 60.0
        dow = event_time.weekday()
        doy = event_time.timetuple().tm_yday
        change_hours = (fingerprint.get("change_proximity") or {}).get("nearest_change_hours")
        change_prox = math.exp(-(change_hours ** 2) / (2 * 24 ** 2)) if change_hours is not None else 0.0
        upgrade_days = (fingerprint.get("vendor_upgrade") or {}).get("days_since_upgrade")
        upgrade_decay = math.exp(-upgrade_days / 30.0) if upgrade_days is not None else 0.0
        load_ratio = (fingerprint.get("traffic_cycle") or {}).get("load_ratio_vs_baseline") or 0.0
        return {
            "norm_timestamp": 0.0,
            "time_of_day_sin": math.sin(2 * math.pi * hour / 24),
            "time_of_day_cos": math.cos(2 * math.pi * hour / 24),
            "day_of_week_sin": math.sin(2 * math.pi * dow / 7),
            "day_of_week_cos": math.cos(2 * math.pi * dow / 7),
            "change_proximity": change_prox,
            "vendor_upgrade_recency": upgrade_decay,
            "traffic_load_ratio": load_ratio,
            "seasonal_sin": math.sin(2 * math.pi * doy / 365),
            "seasonal_cos": math.cos(2 * math.pi * doy / 365),
        }

    # --- Step 4.5: Polarity detection ---

    @staticmethod
    def _detect_polarity(raw_content: str) -> Optional[str]:
        """Simple keyword-based polarity for conflict detection (Mechanism #6)."""
        content_lower = raw_content.lower()
        up_keywords = ["increase", "spike", "up", "surge", "rise", "upgrade"]
        down_keywords = ["decrease", "drop", "down", "loss", "failure", "degrade"]
        up = sum(1 for kw in up_keywords if kw in content_lower)
        down = sum(1 for kw in down_keywords if kw in content_lower)
        if up > down:
            return "UP"
        elif down > up:
            return "DOWN"
        return "NEUTRAL"

    # --- Legacy dual-write ---

    async def _compute_legacy_embeddings(
        self, raw_content, entities, neighbourhood, fingerprint, failure_modes, temporal_context,
    ) -> tuple[Optional[list[float]], Optional[list[float]], list[bool]]:
        """Compute legacy concatenated embeddings for v2 backward compat."""
        # Per LLD: legacy path should persist NULL (None) and mask=False for missing embeddings
        mask = [False, False, True, False]
        enriched = None
        raw_emb = None
        return enriched, raw_emb, mask

    # --- Dedup ---

    def _compute_dedup_key(
        self, tenant_id: str, source_type: str, source_ref: Optional[str], event_ts: datetime,
    ) -> Optional[str]:
        if not source_ref:
            return None
        raw = f"{tenant_id}:{source_type}:{source_ref}:{event_ts.isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:64]
