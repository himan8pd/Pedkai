"""Tests for AbeyanceColdStorage (TASK-205)."""
import os
import sys
import importlib.util
import tempfile
import numpy as np
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path

# Use temp dir for cold storage in tests
os.environ["COLD_STORAGE_BASE_PATH"] = tempfile.mkdtemp(prefix="pedkai_cold_test_")

# Import cold_storage directly to avoid triggering backend/app/services/__init__.py
# which requires SQLAlchemy async drivers and full app settings.
_WORKTREE_ROOT = Path(__file__).resolve().parent.parent
_MODULE_PATH = _WORKTREE_ROOT / "backend" / "app" / "services" / "abeyance" / "cold_storage.py"

_spec = importlib.util.spec_from_file_location("cold_storage", _MODULE_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

AbeyanceColdStorage = _mod.AbeyanceColdStorage
AbeyanceFragment = _mod.AbeyanceFragment


def _make_fragment(dim=8, tenant_id=None) -> AbeyanceFragment:
    tid = tenant_id or str(uuid4())
    return AbeyanceFragment(
        fragment_id=str(uuid4()),
        tenant_id=tid,
        embedding=list(np.random.randn(dim).astype(float)),
        created_at=datetime.now(timezone.utc).isoformat(),
        decay_score=0.9,
        status="ACTIVE",
        corroboration_count=0,
    )


def test_cold_storage_path_deterministic():
    store = AbeyanceColdStorage()
    tid = uuid4()
    p1 = store.cold_storage_path(tid, 2025, 3)
    p2 = store.cold_storage_path(tid, 2025, 3)
    assert str(p1) == str(p2)
    assert "2025" in str(p1)
    assert "03" in str(p1)


def test_archive_creates_directory():
    store = AbeyanceColdStorage()
    frag = _make_fragment()
    path = store.archive_fragment(frag)
    assert os.path.exists(path)


def test_archive_and_retrieve_round_trip():
    store = AbeyanceColdStorage()
    tid = str(uuid4())
    dim = 8
    frag = _make_fragment(dim=dim, tenant_id=tid)
    store.archive_fragment(frag)

    query = np.array(frag.embedding)
    results = store.search_cold(query, top_k=1, tenant_id=UUID(tid) if False else tid)
    assert len(results) >= 1
    # Cosine similarity with itself should be ~1.0
    result_emb = np.array(results[0].embedding)
    cos_sim = float(np.dot(query, result_emb) / (np.linalg.norm(query) * np.linalg.norm(result_emb) + 1e-10))
    assert cos_sim > 0.99


def test_search_returns_top_k():
    store = AbeyanceColdStorage()
    tid = str(uuid4())
    dim = 8
    for _ in range(20):
        frag = _make_fragment(dim=dim, tenant_id=tid)
        store.archive_fragment(frag)

    query = np.random.randn(dim)
    results = store.search_cold(query, top_k=5, tenant_id=tid)
    assert len(results) == 5


def test_search_empty_store_returns_empty_list():
    store = AbeyanceColdStorage()
    tid = str(uuid4())
    query = np.random.randn(8)
    results = store.search_cold(query, top_k=5, tenant_id=tid)
    assert results == []


def test_search_across_multiple_months():
    import tempfile
    os.environ["COLD_STORAGE_BASE_PATH"] = tempfile.mkdtemp(prefix="pedkai_multi_month_")
    store = AbeyanceColdStorage()
    tid = str(uuid4())
    dim = 8

    frag1 = AbeyanceFragment(
        fragment_id=str(uuid4()), tenant_id=tid,
        embedding=list(np.ones(dim, dtype=float)),
        created_at="2024-01-15T00:00:00+00:00",
    )
    frag2 = AbeyanceFragment(
        fragment_id=str(uuid4()), tenant_id=tid,
        embedding=list(np.ones(dim, dtype=float) * 0.5),
        created_at="2024-06-20T00:00:00+00:00",
    )
    store.archive_fragment(frag1)
    store.archive_fragment(frag2)

    query = np.ones(dim)
    results = store.search_cold(query, top_k=5, tenant_id=tid)
    assert len(results) >= 2
