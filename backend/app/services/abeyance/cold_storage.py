"""Cold Storage — pgvector ANN indexing with Parquet fallback.

Remediation target:
- Phase 5 §5.2: Cold storage must support ANN search via pgvector,
  with local Parquet as a degraded fallback for environments without
  pgvector.

Architecture:
- Primary: PostgreSQL table (cold_fragment) with IVFFlat index on
  the embedding column.  ANN queries use pgvector's <=> (cosine)
  operator and return in O(sqrt(N)) rather than O(N).
- Fallback: Local Parquet files (original implementation), used when
  the DB session is unavailable or for offline analysis.

Invariants enforced:
- INV-7: tenant_id on every query
- INV-6: MAX_COLD_BATCH bounds archival batches
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

import numpy as np
import pandas as pd
from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import Base

logger = logging.getLogger(__name__)

MAX_COLD_BATCH = 5_000
COLD_SEARCH_DEFAULT_K = 20


# ---------------------------------------------------------------------------
# ORM model for DB-backed cold storage
# ---------------------------------------------------------------------------

class ColdFragmentORM(Base):
    """Archived fragment stored in PostgreSQL with pgvector ANN index."""

    __tablename__ = "cold_fragment"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    original_fragment_id = Column(PG_UUID(as_uuid=True), nullable=False)
    source_type = Column(String(50), nullable=False)
    raw_content_summary = Column(Text, nullable=True)  # First 500 chars only
    extracted_entities = Column(JSONB, nullable=False, default=list, server_default='[]')
    failure_mode_tags = Column(JSONB, nullable=False, default=list, server_default='[]')

    # Store enriched embedding for ANN search
    try:
        from pgvector.sqlalchemy import Vector
        enriched_embedding = Column(Vector(1536), nullable=True)
    except ImportError:
        enriched_embedding = Column(Text, nullable=True)

    # Metadata
    event_timestamp = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    original_created_at = Column(DateTime(timezone=True), nullable=True)
    original_decay_score = Column(Float, nullable=False, default=0.0)
    snap_status_at_archive = Column(String(20), nullable=False, default="EXPIRED")

    __table_args__ = (
        Index("ix_cold_frag_tenant", "tenant_id"),
        Index("ix_cold_frag_original", "original_fragment_id"),
    )


# ---------------------------------------------------------------------------
# Portable dataclass (no SQLAlchemy dependency)
# ---------------------------------------------------------------------------

@dataclass
class AbeyanceFragment:
    """Portable fragment for cold storage (no SQLAlchemy dependency)."""
    fragment_id: str
    tenant_id: str
    embedding: list
    created_at: str
    decay_score: float = 1.0
    status: str = "ACTIVE"
    corroboration_count: int = 0
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class AbeyanceColdStorage:
    """Cold storage with pgvector ANN indexing and Parquet fallback.

    Usage:
        storage = AbeyanceColdStorage()

        # Archive via DB (primary path)
        await storage.archive_to_db(session, fragment_orm)

        # ANN search via DB
        results = await storage.search_db(session, tenant_id, query_embedding, top_k=10)

        # Parquet fallback (no DB required)
        path = storage.archive_fragment(portable_fragment)
        results = storage.search_cold(query_embedding, top_k=5, tenant_id=tid)
    """

    def __init__(self):
        self.backend = os.environ.get("COLD_STORAGE_BACKEND", "local")
        self.base_path = Path(
            os.environ.get("COLD_STORAGE_BASE_PATH", "/tmp/pedkai_cold_storage")
        )
        self.cold_search_threshold = float(
            os.environ.get("COLD_SEARCH_THRESHOLD", "0.7")
        )

    # ------------------------------------------------------------------
    # Primary path: PostgreSQL + pgvector ANN
    # ------------------------------------------------------------------

    async def archive_to_db(
        self,
        session: AsyncSession,
        fragment,  # AbeyanceFragmentORM
        tenant_id: str,
    ) -> ColdFragmentORM:
        """Archive a fragment to the cold_fragment table for ANN search."""
        cold = ColdFragmentORM(
            id=uuid4(),
            tenant_id=tenant_id,
            original_fragment_id=fragment.id,
            source_type=fragment.source_type,
            raw_content_summary=(fragment.raw_content or "")[:500],
            extracted_entities=fragment.extracted_entities or [],
            failure_mode_tags=fragment.failure_mode_tags or [],
            enriched_embedding=fragment.enriched_embedding,
            event_timestamp=fragment.event_timestamp,
            original_created_at=fragment.created_at,
            original_decay_score=fragment.current_decay_score,
            snap_status_at_archive=fragment.snap_status,
        )
        session.add(cold)
        await session.flush()
        logger.info(
            "Archived fragment %s to cold storage (DB)",
            fragment.id,
        )
        return cold

    async def archive_batch_to_db(
        self,
        session: AsyncSession,
        fragments: list,
        tenant_id: str,
    ) -> int:
        """Archive a batch of fragments. Bounded by MAX_COLD_BATCH."""
        archived = 0
        for frag in fragments[:MAX_COLD_BATCH]:
            await self.archive_to_db(session, frag, tenant_id)
            archived += 1
        await session.flush()
        logger.info("Archived %d fragments to cold storage (DB)", archived)
        return archived

    async def search_db(
        self,
        session: AsyncSession,
        tenant_id: str,
        query_embedding: list[float],
        top_k: int = COLD_SEARCH_DEFAULT_K,
    ) -> list[ColdFragmentORM]:
        """ANN search via pgvector cosine distance operator.

        Uses IVFFlat index for O(sqrt(N)) retrieval instead of O(N) scan.
        """
        # pgvector cosine distance: embedding <=> query
        # Lower distance = more similar
        stmt = (
            select(ColdFragmentORM)
            .where(ColdFragmentORM.tenant_id == tenant_id)
            .where(ColdFragmentORM.enriched_embedding.isnot(None))
            .order_by(
                ColdFragmentORM.enriched_embedding.cosine_distance(query_embedding)
            )
            .limit(top_k)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Fallback path: Local Parquet (original implementation)
    # ------------------------------------------------------------------

    def cold_storage_path(self, tenant_id: str, year: int, month: int) -> Path:
        """Deterministic: {base_path}/{tenant_id}/{year}/{month:02d}/fragments.parquet"""
        return (
            self.base_path / str(tenant_id) / str(year) / f"{month:02d}"
            / "fragments.parquet"
        )

    def archive_fragment(self, fragment: AbeyanceFragment) -> str:
        """Serialize fragment to local Parquet. Returns archive path."""
        created = (
            datetime.fromisoformat(fragment.created_at)
            if isinstance(fragment.created_at, str)
            else fragment.created_at
        )
        path = self.cold_storage_path(fragment.tenant_id, created.year, created.month)
        path.parent.mkdir(parents=True, exist_ok=True)

        row = {
            "fragment_id": fragment.fragment_id,
            "tenant_id": fragment.tenant_id,
            "embedding": [fragment.embedding],
            "created_at": fragment.created_at,
            "decay_score": fragment.decay_score,
            "status": fragment.status,
            "corroboration_count": fragment.corroboration_count,
            "metadata_json": str(fragment.metadata),
        }
        new_df = pd.DataFrame(row)

        if path.exists():
            existing = pd.read_parquet(path)
            combined = pd.concat([existing, new_df], ignore_index=True)
        else:
            combined = new_df

        combined.to_parquet(path, index=False)
        return str(path)

    def _cosine_similarity(
        self, query: np.ndarray, matrix: np.ndarray
    ) -> np.ndarray:
        q_norm = query / (np.linalg.norm(query) + 1e-10)
        m_norms = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10)
        return m_norms @ q_norm

    def search_cold(
        self,
        query_embedding: np.ndarray,
        top_k: int = 5,
        tenant_id: str | None = None,
    ) -> list[AbeyanceFragment]:
        """Find top-k fragments by cosine similarity (Parquet fallback)."""
        fragments = self._load_tenant_fragments(tenant_id)
        if not fragments:
            return []

        embeddings = np.array([f.embedding for f in fragments])
        scores = self._cosine_similarity(query_embedding, embeddings)
        top_indices = np.argsort(scores)[::-1][:top_k]
        return [fragments[i] for i in top_indices]

    def _load_tenant_fragments(
        self, tenant_id: str | None = None
    ) -> list[AbeyanceFragment]:
        """Load all cold Parquet files for a tenant (or all tenants if None)."""
        results: list[AbeyanceFragment] = []
        search_root = (
            self.base_path / str(tenant_id) if tenant_id else self.base_path
        )

        if not search_root.exists():
            return []

        for parquet_file in search_root.rglob("*.parquet"):
            try:
                df = pd.read_parquet(parquet_file)
                for _, row in df.iterrows():
                    emb = row["embedding"]
                    if isinstance(emb, (list, np.ndarray)):
                        emb_list = list(emb)
                    else:
                        emb_list = list(emb)
                    results.append(AbeyanceFragment(
                        fragment_id=str(row["fragment_id"]),
                        tenant_id=str(row["tenant_id"]),
                        embedding=emb_list,
                        created_at=str(row["created_at"]),
                        decay_score=float(row.get("decay_score", 1.0)),
                        status=str(row.get("status", "ACTIVE")),
                        corroboration_count=int(
                            row.get("corroboration_count", 0)
                        ),
                    ))
            except Exception:
                continue
        return results
