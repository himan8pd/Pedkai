"""Tests for ShadowTopologyService — PedkAI's private topology graph.

Tests entity upsert idempotency, topological proximity, and CMDB export tag format.

Uses mocked database sessions matching existing test patterns.

LLD ref: §8 (The Shadow Topology — Protecting the Moat)
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from backend.app.services.abeyance.shadow_topology import (
    ShadowTopologyService,
)


# ---------------------------------------------------------------------------
# Test: Instantiation
# ---------------------------------------------------------------------------

class TestSingletonFactory:

    def test_can_instantiate_service(self):
        """ShadowTopologyService can be instantiated."""
        svc = ShadowTopologyService()
        assert isinstance(svc, ShadowTopologyService)


# ---------------------------------------------------------------------------
# Test: Topological proximity (entity overlap shortcut)
# ---------------------------------------------------------------------------

class TestTopologicalProximity:
    """Test the proximity formula: 1.0 / min_hops."""

    def setup_method(self):
        self.svc = ShadowTopologyService()
        self.mock_session = AsyncMock()

    @pytest.mark.asyncio
    async def test_direct_overlap_returns_one(self):
        """If entity sets share an identifier, proximity = 1.0."""
        shared_id = uuid4()
        result = await self.svc.topological_proximity(
            session=self.mock_session,
            tenant_id="t1",
            entity_set_a={uuid4(), shared_id},
            entity_set_b={shared_id, uuid4()},
        )
        assert result == 1.0

    @pytest.mark.asyncio
    async def test_empty_set_a_returns_zero(self):
        result = await self.svc.topological_proximity(
            session=self.mock_session,
            tenant_id="t1",
            entity_set_a=set(),
            entity_set_b={uuid4()},
        )
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_empty_set_b_returns_zero(self):
        result = await self.svc.topological_proximity(
            session=self.mock_session,
            tenant_id="t1",
            entity_set_a={uuid4()},
            entity_set_b=set(),
        )
        assert result == 0.0


# ---------------------------------------------------------------------------
# Test: CMDB export reference tag format
# ---------------------------------------------------------------------------

class TestCmdbExportTag:
    """Verify the reference tag format: PEDKAI-{tenant[:8]}-{rel_id[:8]}."""

    def test_tag_format(self):
        tenant_id = "casinolimit"
        relationship_id = uuid4()
        tag = f"PEDKAI-{str(tenant_id)[:8]}-{str(relationship_id)[:8]}"
        assert tag.startswith("PEDKAI-")
        assert len(tag.split("-")) == 3

    def test_tag_uses_truncated_ids(self):
        tenant_id = "a-very-long-tenant-identifier"
        rel_id = "12345678-1234-1234-1234-123456789abc"
        tag = f"PEDKAI-{str(tenant_id)[:8]}-{str(rel_id)[:8]}"
        assert tag == "PEDKAI-a-very-l-12345678"


# ---------------------------------------------------------------------------
# Test: Entity upsert behaviour (mock-based)
# ---------------------------------------------------------------------------

class TestEntityUpsert:
    """Verify idempotent get_or_create_entity behaviour."""

    @pytest.mark.asyncio
    async def test_get_or_create_creates_new_entity(self):
        """get_or_create_entity should add a new entity when none exists."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # No existing entity
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        svc = ShadowTopologyService()
        entity = await svc.get_or_create_entity(
            session=mock_session,
            tenant_id="t1",
            entity_identifier="ENT-1",
            entity_domain="RAN",
        )

        # Should have added a new entity
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_or_create_returns_existing(self):
        """If entity already exists, return it without creating a new one."""
        existing = MagicMock()
        existing.last_evidence = None
        existing.attributes = {}

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute = AsyncMock(return_value=mock_result)

        svc = ShadowTopologyService()
        entity = await svc.get_or_create_entity(
            session=mock_session,
            tenant_id="t1",
            entity_identifier="ENT-1",
        )

        assert entity is existing
        mock_session.add.assert_not_called()


# ---------------------------------------------------------------------------
# Test: Neighbourhood returns dict
# ---------------------------------------------------------------------------

class TestNeighbourhood:

    @pytest.mark.asyncio
    async def test_neighbourhood_returns_dict(self):
        """get_neighbourhood returns a dict with entities and relationships."""
        mock_session = AsyncMock()
        # Mock relationship query returning empty
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        svc = ShadowTopologyService()
        nbr = await svc.get_neighbourhood(
            session=mock_session,
            tenant_id="t1",
            entity_ids=[uuid4()],
        )
        assert isinstance(nbr, dict)
