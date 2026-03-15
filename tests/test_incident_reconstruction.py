"""Tests for IncidentReconstructionService — timeline assembly from fragment history.

Tests time-ordered fragments, cluster context inclusion, snap history,
and handling of no-match scenarios.

Uses mocked database sessions.

LLD ref: Incident Reconstruction
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.app.services.abeyance.incident_reconstruction import (
    IncidentReconstructionService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_fragment(
    fragment_id=None,
    event_timestamp=None,
    created_at=None,
    source_type="ALARM",
    snap_status="ABEYANCE",
    raw_content="Test alarm",
    failure_mode_tags=None,
    current_decay_score=0.8,
    snapped_hypothesis_id=None,
    updated_at=None,
):
    frag = MagicMock()
    frag.id = fragment_id or uuid4()
    frag.event_timestamp = event_timestamp
    frag.created_at = created_at or datetime.now(timezone.utc)
    frag.source_type = source_type
    frag.snap_status = snap_status
    frag.raw_content = raw_content
    frag.failure_mode_tags = failure_mode_tags or []
    frag.current_decay_score = current_decay_score
    frag.snapped_hypothesis_id = snapped_hypothesis_id
    frag.updated_at = updated_at
    return frag


# ---------------------------------------------------------------------------
# Test: Timeline building
# ---------------------------------------------------------------------------

class TestTimelineBuilding:
    """Verify the _build_timeline method."""

    def setup_method(self):
        self.svc = IncidentReconstructionService(MagicMock())

    def test_fragments_appear_in_timeline(self):
        now = datetime.now(timezone.utc)
        frags = [
            _mock_fragment(event_timestamp=now - timedelta(hours=2)),
            _mock_fragment(event_timestamp=now),
        ]
        timeline = self.svc._build_timeline(frags, [], [])
        assert len(timeline) == 2
        assert all(e["type"] == "fragment" for e in timeline)

    def test_timeline_is_time_ordered(self):
        now = datetime.now(timezone.utc)
        frags = [
            _mock_fragment(event_timestamp=now),
            _mock_fragment(event_timestamp=now - timedelta(hours=2)),
        ]
        timeline = self.svc._build_timeline(frags, [], [])
        # Should be sorted by timestamp
        timestamps = [e["timestamp"] for e in timeline]
        assert timestamps == sorted(timestamps)

    def test_snap_events_included(self):
        now = datetime.now(timezone.utc)
        frags = [_mock_fragment(event_timestamp=now)]

        from backend.app.schemas.abeyance import SnapHistoryEntry
        snaps = [SnapHistoryEntry(
            fragment_id=uuid4(),
            snapped_to=uuid4(),
            snap_score=0.85,
            failure_mode="DARK_EDGE",
            snapped_at=now,
        )]
        timeline = self.svc._build_timeline(frags, snaps, [])
        snap_entries = [e for e in timeline if e["type"] == "snap"]
        assert len(snap_entries) == 1

    def test_cluster_events_included(self):
        now = datetime.now(timezone.utc)
        frags = [_mock_fragment(event_timestamp=now)]

        from backend.app.schemas.abeyance import AccumulationClusterResponse
        clusters = [AccumulationClusterResponse(
            cluster_id="test-cluster",
            member_fragment_ids=[uuid4(), uuid4(), uuid4()],
            member_count=3,
            cluster_score=0.75,
            strongest_failure_mode="DARK_EDGE",
        )]
        timeline = self.svc._build_timeline(frags, [], clusters)
        cluster_entries = [e for e in timeline if e["type"] == "cluster"]
        assert len(cluster_entries) == 1

    def test_empty_fragments_empty_timeline(self):
        timeline = self.svc._build_timeline([], [], [])
        assert timeline == []


# ---------------------------------------------------------------------------
# Test: Primary failure mode extraction
# ---------------------------------------------------------------------------

class TestPrimaryFailureMode:

    def setup_method(self):
        self.svc = IncidentReconstructionService(MagicMock())

    def test_highest_confidence_selected(self):
        frag = _mock_fragment(failure_mode_tags=[
            {"divergence_type": "DARK_EDGE", "confidence": 0.3},
            {"divergence_type": "DARK_NODE", "confidence": 0.8},
        ])
        mode = self.svc._primary_failure_mode(frag)
        assert mode == "DARK_NODE"

    def test_empty_tags_returns_none(self):
        frag = _mock_fragment(failure_mode_tags=[])
        mode = self.svc._primary_failure_mode(frag)
        assert mode is None

    def test_none_tags_returns_none(self):
        frag = _mock_fragment(failure_mode_tags=None)
        frag.failure_mode_tags = None
        mode = self.svc._primary_failure_mode(frag)
        assert mode is None


# ---------------------------------------------------------------------------
# Test: Snap history extraction
# ---------------------------------------------------------------------------

class TestSnapHistoryExtraction:

    def setup_method(self):
        self.svc = IncidentReconstructionService(MagicMock())

    def test_snapped_fragments_produce_snap_entries(self):
        hyp_id = uuid4()
        now = datetime.now(timezone.utc)
        frags = [
            _mock_fragment(
                snap_status="SNAPPED",
                snapped_hypothesis_id=hyp_id,
                updated_at=now,
            ),
        ]
        snaps = self.svc._extract_snap_history(frags)
        assert len(snaps) == 1
        assert snaps[0].snapped_to == hyp_id

    def test_abeyance_fragments_no_snap_entries(self):
        frags = [_mock_fragment(snap_status="ABEYANCE")]
        snaps = self.svc._extract_snap_history(frags)
        assert len(snaps) == 0
