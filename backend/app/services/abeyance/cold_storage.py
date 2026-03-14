"""Cold storage for Abeyance Memory fragments.

Saves fragments (with embeddings) to local Parquet files.
Supports cosine similarity search over cold storage.

Backend: COLD_STORAGE_BACKEND env var ('local' default, 's3' future)
Base path: COLD_STORAGE_BASE_PATH env var (default: /tmp/pedkai_cold_storage)
"""
import os
import numpy as np
import pandas as pd
from pathlib import Path
from uuid import UUID
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AbeyanceFragment:
    """Portable fragment for cold storage (no SQLAlchemy dependency)."""
    fragment_id: str
    tenant_id: str
    embedding: list  # list[float], embedding dimension varies
    created_at: str  # ISO datetime string
    decay_score: float = 1.0
    status: str = "ACTIVE"
    corroboration_count: int = 0
    metadata: dict = field(default_factory=dict)


class AbeyanceColdStorage:
    def __init__(self):
        self.backend = os.environ.get("COLD_STORAGE_BACKEND", "local")
        self.base_path = Path(os.environ.get("COLD_STORAGE_BASE_PATH", "/tmp/pedkai_cold_storage"))
        self.cold_search_threshold = float(os.environ.get("COLD_SEARCH_THRESHOLD", "0.7"))

    def cold_storage_path(self, tenant_id, year: int, month: int) -> Path:
        """Deterministic: {base_path}/{tenant_id}/{year}/{month:02d}/fragments.parquet"""
        return self.base_path / str(tenant_id) / str(year) / f"{month:02d}" / "fragments.parquet"

    def archive_fragment(self, fragment: AbeyanceFragment) -> str:
        """Serialize fragment to local Parquet. Returns archive path."""
        created = datetime.fromisoformat(fragment.created_at) if isinstance(fragment.created_at, str) else fragment.created_at
        path = self.cold_storage_path(fragment.tenant_id, created.year, created.month)
        path.parent.mkdir(parents=True, exist_ok=True)

        row = {
            "fragment_id": fragment.fragment_id,
            "tenant_id": fragment.tenant_id,
            "embedding": [fragment.embedding],  # store as list-of-lists for parquet
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

    def _cosine_similarity(self, query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
        q_norm = query / (np.linalg.norm(query) + 1e-10)
        m_norms = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10)
        return m_norms @ q_norm

    def search_cold(self, query_embedding: np.ndarray, top_k: int = 5, tenant_id=None) -> list:
        """Find top-k fragments by cosine similarity. Returns list of AbeyanceFragment."""
        fragments = self._load_tenant_fragments(tenant_id)
        if not fragments:
            return []

        embeddings = np.array([f.embedding for f in fragments])
        scores = self._cosine_similarity(query_embedding, embeddings)
        top_indices = np.argsort(scores)[::-1][:top_k]
        return [fragments[i] for i in top_indices]

    def _load_tenant_fragments(self, tenant_id=None) -> list:
        """Load all cold Parquet files for a tenant (or all tenants if None)."""
        results = []
        search_root = self.base_path / str(tenant_id) if tenant_id else self.base_path

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
                        corroboration_count=int(row.get("corroboration_count", 0)),
                    ))
            except Exception:
                continue
        return results
