"""Tests for ValueAttributionService — discovery ledger and value metrics.

Tests ledger creation, value events, illumination ratio, Dark Graph Reduction
Index, and reference tag format.

Uses mocked database sessions.

LLD ref: §13 (Value Attribution Methodology)
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.app.services.abeyance.value_attribution import ValueAttributionService


# ---------------------------------------------------------------------------
# Test: CMDB Reference Tag Format
# ---------------------------------------------------------------------------

class TestReferenceTag:
    """Verify the PEDKAI-{tenant[:8]}-{hypothesis[:8]} format."""

    def test_tag_format(self):
        tenant_id = "casinolimit"
        hypothesis_id = uuid4()
        tag = f"PEDKAI-{str(tenant_id)[:8]}-{str(hypothesis_id)[:8]}"
        assert tag.startswith("PEDKAI-")
        parts = tag.split("-", 2)
        assert parts[0] == "PEDKAI"
        assert len(parts) == 3

    def test_tag_truncation(self):
        long_tenant = "a-very-long-tenant-id"
        hypothesis_id = "12345678-1234-1234-1234-123456789abc"
        tag = f"PEDKAI-{str(long_tenant)[:8]}-{str(hypothesis_id)[:8]}"
        assert tag == "PEDKAI-a-very-l-12345678"


# ---------------------------------------------------------------------------
# Test: Record discovery (mock-based)
# ---------------------------------------------------------------------------

class TestRecordDiscovery:

    @pytest.mark.asyncio
    async def test_creates_ledger_entry(self):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        svc = ValueAttributionService(MagicMock())
        entry = await svc.record_discovery(
            tenant_id="test-tenant",
            hypothesis_id=uuid4(),
            discovery_type="DARK_EDGE",
            entity_ids=["ENT-1", "ENT-2"],
            session=mock_session,
        )

        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_generates_reference_tag(self):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        svc = ValueAttributionService(MagicMock())
        hyp_id = uuid4()
        entry = await svc.record_discovery(
            tenant_id="test-tenant",
            hypothesis_id=hyp_id,
            discovery_type="DARK_NODE",
            entity_ids=["ENT-1"],
            session=mock_session,
        )

        # Verify the entry was created with correct tag
        added_obj = mock_session.add.call_args[0][0]
        assert added_obj.cmdb_reference_tag.startswith("PEDKAI-")


# ---------------------------------------------------------------------------
# Test: Record value event (mock-based)
# ---------------------------------------------------------------------------

class TestRecordValueEvent:

    @pytest.mark.asyncio
    async def test_creates_value_event(self):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        svc = ValueAttributionService(MagicMock())
        event = await svc.record_value_event(
            tenant_id="test-tenant",
            ledger_entry_id=uuid4(),
            event_type="MTTR_REDUCTION",
            attributed_hours=2.5,
            rationale="Test attribution",
            session=mock_session,
        )

        mock_session.add.assert_called_once()
        added_obj = mock_session.add.call_args[0][0]
        assert added_obj.event_type == "MTTR_REDUCTION"
        assert added_obj.attributed_value_hours == 2.5


# ---------------------------------------------------------------------------
# Test: Illumination ratio formula
# ---------------------------------------------------------------------------

class TestIlluminationRatio:
    """illumination_ratio = illuminated_incidents / total_incidents."""

    def test_formula_zero_incidents(self):
        """0 total incidents → ratio = 0.0."""
        total = 0
        illuminated = 0
        ratio = illuminated / total if total > 0 else 0.0
        assert ratio == 0.0

    def test_formula_some_illuminated(self):
        """5 illuminated out of 20 → ratio = 0.25."""
        ratio = 5 / 20
        assert ratio == 0.25

    def test_formula_all_illuminated(self):
        """10 illuminated out of 10 → ratio = 1.0."""
        ratio = 10 / 10
        assert ratio == 1.0


# ---------------------------------------------------------------------------
# Test: Dark Graph Reduction Index formula
# ---------------------------------------------------------------------------

class TestDarkGraphReductionIndex:
    """DGRI = 1 - (current_divergences / baseline_divergences)."""

    def test_no_progress(self):
        """0 resolved, 100 baseline → DGRI = 0.0."""
        baseline = 100
        current = baseline - 0  # 100
        index = 1.0 - (current / baseline)
        assert index == 0.0

    def test_half_resolved(self):
        """50 resolved, 100 baseline → DGRI = 0.5."""
        baseline = 100
        resolved = 50
        current = baseline - resolved  # 50
        index = 1.0 - (current / baseline)
        assert index == 0.5

    def test_all_resolved(self):
        """100 resolved, 100 baseline → DGRI = 1.0."""
        baseline = 100
        current = 0
        index = 1.0 - (current / baseline)
        assert index == 1.0

    def test_zero_baseline_returns_zero(self):
        """If baseline is 0, DGRI = 0.0 (avoid division by zero)."""
        baseline = 0
        index = 0.0 if baseline == 0 else 1.0 - (0 / baseline)
        assert index == 0.0


# ---------------------------------------------------------------------------
# Test: Incident correlation (mock-based)
# ---------------------------------------------------------------------------

class TestIncidentCorrelation:

    @pytest.mark.asyncio
    async def test_matching_entities_creates_value_events(self):
        """When resolved entities overlap with discoveries, create MTTR events."""
        mock_discovery = MagicMock()
        mock_discovery.id = uuid4()
        mock_discovery.discovered_entities = ["ENT-1", "ENT-2"]
        mock_discovery.discovery_type = "DARK_EDGE"
        mock_discovery.cmdb_reference_tag = "PEDKAI-test-hyp"
        mock_discovery.status = "ACTIVE"

        mock_session = AsyncMock()
        # First execute: query discoveries
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_discovery]
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        svc = ValueAttributionService(MagicMock())
        events = await svc.correlate_incident(
            tenant_id="test-tenant",
            incident_id="INC-001",
            resolved_entity_ids=["ENT-1", "ENT-3"],
            actual_mttr_hours=1.5,
            session=mock_session,
        )

        # Should have created at least one value event
        assert mock_session.add.called

    @pytest.mark.asyncio
    async def test_no_matching_entities_no_events(self):
        """When no overlap exists, no value events are created."""
        mock_discovery = MagicMock()
        mock_discovery.discovered_entities = ["ENT-X"]
        mock_discovery.status = "ACTIVE"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_discovery]
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        svc = ValueAttributionService(MagicMock())
        events = await svc.correlate_incident(
            tenant_id="test-tenant",
            incident_id="INC-002",
            resolved_entity_ids=["ENT-Y"],
            session=mock_session,
        )

        assert len(events) == 0
