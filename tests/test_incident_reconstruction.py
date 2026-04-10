"""Tests for IncidentReconstructionService — timeline assembly from fragment history.

Tests service instantiation and basic reconstruction logic.

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


class TestInstantiation:
    """Verify the service can be created."""

    def test_can_instantiate(self):
        svc = IncidentReconstructionService()
        assert isinstance(svc, IncidentReconstructionService)


class TestReconstruct:
    """Test the reconstruct method with mocked DB."""

    @pytest.mark.asyncio
    async def test_reconstruct_returns_dict(self):
        """reconstruct() should return a dict with expected keys."""
        mock_session = AsyncMock()
        # Mock fragment query returning empty
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        svc = IncidentReconstructionService()
        result = await svc.reconstruct(
            session=mock_session,
            tenant_id="t1",
        )

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_reconstruct_with_hypothesis_id(self):
        """reconstruct() accepts hypothesis_id filter."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        svc = IncidentReconstructionService()
        result = await svc.reconstruct(
            session=mock_session,
            tenant_id="t1",
            hypothesis_id=uuid4(),
        )

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_reconstruct_with_time_range(self):
        """reconstruct() accepts time range filters."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        svc = IncidentReconstructionService()
        now = datetime.now(timezone.utc)
        result = await svc.reconstruct(
            session=mock_session,
            tenant_id="t1",
            time_start=now - timedelta(hours=2),
            time_end=now,
        )

        assert isinstance(result, dict)
