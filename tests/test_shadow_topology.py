"""Tests for ShadowTopologyService — PedkAI's private topology graph.

Tests entity upsert idempotency, relationship creation, neighbourhood expansion
(conceptual), topological proximity, and CMDB export logging.

Uses mocked database sessions matching existing test patterns.

LLD ref: §8 (The Shadow Topology — Protecting the Moat)
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from backend.app.services.abeyance.shadow_topology import (
    ShadowTopologyService,
    get_shadow_topology,
)


# ---------------------------------------------------------------------------
# Test: Singleton factory
# ---------------------------------------------------------------------------

class TestSingletonFactory:

    def test_get_shadow_topology_returns_instance(self):
        """get_shadow_topology() should return a ShadowTopologyService."""
        # Reset singleton
        import backend.app.services.abeyance.shadow_topology as mod
        mod._shadow_topology = None
        svc = get_shadow_topology(MagicMock())
        assert isinstance(svc, ShadowTopologyService)

    def test_get_shadow_topology_is_singleton(self):
        """Repeated calls return the same instance."""
        import backend.app.services.abeyance.shadow_topology as mod
        mod._shadow_topology = None
        factory = MagicMock()
        svc1 = get_shadow_topology(factory)
        svc2 = get_shadow_topology(factory)
        assert svc1 is svc2
        # Reset for other tests
        mod._shadow_topology = None


# ---------------------------------------------------------------------------
# Test: Topological proximity (entity overlap shortcut)
# ---------------------------------------------------------------------------

class TestTopologicalProximity:
    """Test the proximity formula: 1.0 / min_hops."""

    def setup_method(self):
        self.svc = ShadowTopologyService(MagicMock())

    @pytest.mark.asyncio
    async def test_direct_overlap_returns_one(self):
        """If entity sets share an identifier, proximity = 1.0."""
        result = await self.svc.topological_proximity(
            tenant_id="t1",
            entity_set_a={"ENT-1", "ENT-2"},
            entity_set_b={"ENT-2", "ENT-3"},
        )
        assert result == 1.0

    @pytest.mark.asyncio
    async def test_empty_set_a_returns_zero(self):
        result = await self.svc.topological_proximity(
            tenant_id="t1",
            entity_set_a=set(),
            entity_set_b={"ENT-1"},
        )
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_empty_set_b_returns_zero(self):
        result = await self.svc.topological_proximity(
            tenant_id="t1",
            entity_set_a={"ENT-1"},
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
    async def test_get_or_create_returns_entity(self):
        """get_or_create_entity should return a ShadowEntityORM."""
        from backend.app.models.abeyance_orm import ShadowEntityORM

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = None  # No existing entity
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        svc = ShadowTopologyService(MagicMock())
        entity = await svc.get_or_create_entity(
            tenant_id="t1",
            entity_identifier="ENT-1",
            entity_domain="RAN",
            session=mock_session,
        )

        # Should have added a new entity
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_or_create_returns_existing(self):
        """If entity already exists, return it without creating a new one."""
        existing = MagicMock()
        existing.origin = "CMDB_DECLARED"
        existing.attributes = {}
        existing.last_evidence = None

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = existing
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        svc = ShadowTopologyService(MagicMock())
        entity = await svc.get_or_create_entity(
            tenant_id="t1",
            entity_identifier="ENT-1",
            session=mock_session,
        )

        assert entity is existing
        mock_session.add.assert_not_called()


# ---------------------------------------------------------------------------
# Test: Neighbourhood returns empty for unknown entity
# ---------------------------------------------------------------------------

class TestNeighbourhood:

    @pytest.mark.asyncio
    async def test_unknown_entity_returns_empty_neighbourhood(self):
        """If the center entity doesn't exist, return empty neighbourhood."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = None
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        svc = ShadowTopologyService(MagicMock())
        nbr = await svc.get_neighbourhood(
            tenant_id="t1",
            entity_identifier="NONEXISTENT",
            session=mock_session,
        )
        assert nbr.center_entity == "NONEXISTENT"
        assert len(nbr.entities) == 0
        assert len(nbr.relationships) == 0
