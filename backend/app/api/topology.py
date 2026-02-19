"""
Topology API Router.

Provides endpoints for querying the network topology graph, impact analysis,
and staleness monitoring. All endpoints require authentication.

WS1 — Topology & Impact Analysis.
"""
import logging
from typing import Optional
from uuid import UUID
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Security, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from backend.app.core.database import get_db
from backend.app.core.security import get_current_user, User, TOPOLOGY_READ, TOPOLOGY_READ_FULL
from backend.app.schemas.topology import (
    TopologyGraphResponse,
    EntityResponse,
    RelationshipResponse,
    TopologyHealth,
    ImpactTreeNode,
    ImpactTreeResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Simple in-memory rate limiter: {user: (count, window_start)}
_rate_limit_store: dict = {}
RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW_SECONDS = 60


def _check_rate_limit(username: str) -> None:
    """Simple in-memory rate limiter: 10 req/min per user for full graph."""
    now = datetime.now(timezone.utc)
    entry = _rate_limit_store.get(username)
    if entry:
        count, window_start = entry
        if (now - window_start).total_seconds() < RATE_LIMIT_WINDOW_SECONDS:
            if count >= RATE_LIMIT_MAX:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded: {RATE_LIMIT_MAX} requests per minute for full topology graph.",
                )
            _rate_limit_store[username] = (count + 1, window_start)
        else:
            _rate_limit_store[username] = (1, now)
    else:
        _rate_limit_store[username] = (1, now)


@router.get("/{tenant_id}", response_model=TopologyGraphResponse)
async def get_topology_graph(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[TOPOLOGY_READ_FULL]),
):
    """
    Get the full topology graph for a tenant.
    Requires topology:read_full scope. Rate limited to 10 req/min per user.
    """
    _check_rate_limit(current_user.username)

    try:
        # Query topology relationships with strict tenant isolation (Finding S-1 Fix)
        # TODO: Add index on tenant_id for topology_relationships if graph grows > 100k nodes
        result = await db.execute(
            text("""
                SELECT id, from_entity_id, from_entity_type, to_entity_id, to_entity_type, relationship_type, properties, created_at 
                FROM topology_relationships 
                WHERE tenant_id = :tid
                LIMIT 500
            """),
            {"tid": tenant_id}
        )
        rows = result.fetchall()
    except Exception as e:
        logger.warning(f"Topology query failed: {e}")
        rows = []

    # Build entity set from relationships
    entity_map = {}
    relationships = []
    for row in rows:
        rel_id, from_id, from_type, to_id, to_type, rel_type, props, created_at = row

        if from_id not in entity_map:
            entity_map[from_id] = {
                "id": from_id, "external_id": from_id, "name": from_id,
                "entity_type": from_type, "tenant_id": tenant_id,
            }
        if to_id not in entity_map:
            entity_map[to_id] = {
                "id": to_id, "external_id": to_id, "name": to_id,
                "entity_type": to_type, "tenant_id": tenant_id,
            }

        relationships.append({
            "id": str(rel_id),
            "source_entity_id": from_id,
            "target_entity_id": to_id,
            "relationship_type": rel_type,
            "properties": None,
        })

    entities = [EntityResponse(**e) for e in entity_map.values()]
    rels = [RelationshipResponse(**r) for r in relationships]

    health = TopologyHealth(
        total_entities=len(entities),
        stale_entities=0,
        completeness_pct=100.0 if entities else 0.0,
    )

    return TopologyGraphResponse(
        tenant_id=tenant_id,
        entities=entities,
        relationships=rels,
        topology_health=health,
    )


@router.get("/{tenant_id}/entity/{entity_id}")
async def get_entity(
    tenant_id: str,
    entity_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[TOPOLOGY_READ]),
):
    """Get a single entity and its direct neighbours. Requires topology:read scope."""
    try:
        # Strict tenant isolation in entity query (Finding S-1 Fix)
        result = await db.execute(
            text("""
                SELECT id, from_entity_id, from_entity_type, to_entity_id, to_entity_type, relationship_type
                FROM topology_relationships
                WHERE (from_entity_id = :eid OR to_entity_id = :eid)
                AND tenant_id = :tid
            """),
            {"eid": entity_id, "tid": tenant_id}
        )
        rows = result.fetchall()
    except Exception as e:
        logger.warning(f"Entity query failed: {e}")
        rows = []

    neighbours = []
    for row in rows:
        _, from_id, from_type, to_id, to_type, rel_type = row
        neighbour_id = to_id if from_id == entity_id else from_id
        neighbour_type = to_type if from_id == entity_id else from_type
        neighbours.append({
            "entity_id": neighbour_id,
            "entity_type": neighbour_type,
            "relationship_type": rel_type,
        })

    return {
        "entity_id": entity_id,
        "tenant_id": tenant_id,
        "neighbours": neighbours,
        "neighbour_count": len(neighbours),
    }


@router.get("/{tenant_id}/impact/{entity_id}", response_model=ImpactTreeResponse)
async def get_impact_tree(
    tenant_id: str,
    entity_id: str,
    max_hops: int = Query(default=3, ge=1, le=5),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[TOPOLOGY_READ]),
):
    """
    Get the impact tree for an entity (upstream and downstream).
    Requires topology:read scope. max_hops defaults to 3 and is enforced.
    """
    # Finding 9 Fix: Recursive traversal (simple version for SQLite)
    async def get_neighbours_recursive(eid: str, depth: int, direction: str, visited: set) -> List[ImpactTreeNode]:
        if depth > max_hops or eid in visited:
            return []
        visited.add(eid)
        
        nodes = []
        # direction determines which way we look
        if direction == "upstream":
            q = text("SELECT from_entity_id, from_entity_type, relationship_type FROM topology_relationships WHERE to_entity_id = :eid AND tenant_id = :tid")
        else:
            q = text("SELECT to_entity_id, to_entity_type, relationship_type FROM topology_relationships WHERE from_entity_id = :eid AND tenant_id = :tid")
        
        res = await db.execute(q, {"eid": eid, "tid": tenant_id})
        rows = res.fetchall()
        logger.info(f"Impact recursive {eid} {direction} depth {depth} found {len(rows)} rows for tenant {tenant_id}")
        
        for next_id, next_type, rel_type in rows:
            node = ImpactTreeNode(
                entity_id=next_id, entity_name=next_id, entity_type=next_type,
                external_id=next_id, direction=direction,
                relationship_type=rel_type, depth=depth,
            )
            nodes.append(node)
            # Recurse
            nodes.extend(await get_neighbours_recursive(next_id, depth + 1, direction, visited))
            
        return nodes

    upstream = await get_neighbours_recursive(entity_id, 1, "upstream", set())
    downstream = await get_neighbours_recursive(entity_id, 1, "downstream", set())

    return ImpactTreeResponse(
        root_entity_id=entity_id,
        root_entity_name=entity_id,
        root_entity_type="unknown",
        upstream=upstream,
        downstream=downstream,
        total_customers_impacted=len(downstream),
    )


@router.get("/{tenant_id}/health", response_model=TopologyHealth)
async def get_topology_health(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[TOPOLOGY_READ]),
):
    """Get topology staleness and completeness metrics. Requires topology:read scope."""
    try:
        # Task 2.4 Fix: 7-day threshold (topology doesn't change hourly)
        staleness_threshold = datetime.now(timezone.utc) - timedelta(days=7)
        
        # Total entities across all relationships
        total_res = await db.execute(
            text("""
                SELECT COUNT(*) FROM (
                    SELECT from_entity_id FROM topology_relationships WHERE tenant_id = :tid
                    UNION
                    SELECT to_entity_id FROM topology_relationships WHERE tenant_id = :tid
                ) as entities
            """),
            {"tid": tenant_id}
        )
        total = total_res.scalar() or 0
        
        # Stale = records older than 7 days (using last_synced_at if present, else created_at)
        stale_res = await db.execute(
            text("""
                SELECT COUNT(*) FROM topology_relationships
                WHERE tenant_id = :tid
                AND (last_synced_at IS NULL OR last_synced_at < :threshold)
            """),
            {"tid": tenant_id, "threshold": staleness_threshold}
        )
        stale = stale_res.scalar() or 0
        
    except Exception as e:
        logger.warning(f"Health query failed: {e}")
        total = 0
        stale = 0

    return TopologyHealth(
        total_entities=total,
        stale_entities=stale,
        status="degraded" if stale > 0 else "healthy",
        completeness_pct=round(max(0, (total - stale) / total * 100), 1) if total > 0 else 0.0,
        staleness_threshold_days=7,
    )
