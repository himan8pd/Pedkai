"""
Topology API Router.

Provides endpoints for querying the network topology graph, impact analysis,
and staleness monitoring. All endpoints require authentication.

WS1 — Topology & Impact Analysis.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.security import (
    TOPOLOGY_READ,
    TOPOLOGY_READ_FULL,
    User,
    get_current_user,
)
from backend.app.schemas.topology import (
    EntityResponse,
    ImpactTreeNode,
    ImpactTreeResponse,
    RelationshipResponse,
    TopologyGraphResponse,
    TopologyHealth,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Simple in-memory rate limiter: {user: (count, window_start)}
# Protected by _rate_limit_lock for atomic check-and-increment.
_rate_limit_store: dict = {}
_rate_limit_lock = asyncio.Lock()
RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW_SECONDS = 60


async def _check_rate_limit(username: str) -> None:
    """In-memory rate limiter: 10 req/min per user for full graph. Thread-safe."""
    now = datetime.now(timezone.utc)
    async with _rate_limit_lock:
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
    entity_type: Optional[str] = Query(
        None, description="Filter by entity type (e.g. SITE, GNODEB, CELL)"
    ),
    limit: int = Query(1000, ge=10, le=5000, description="Max relationships to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[TOPOLOGY_READ_FULL]),
):
    """
    Get the topology graph for a tenant.
    Requires topology:read_full scope. Rate limited to 10 req/min per user.

    For large datasets (e.g. Telco2 with 784K entities) this endpoint returns
    a bounded subset.  Use ``entity_type`` to focus on a specific layer
    (SITE, GNODEB, CELL, etc.) and ``limit`` to control result size.

    Entity names and external_ids are resolved from the ``network_entities``
    table so the frontend shows human-readable labels instead of raw UUIDs.
    """
    await _check_rate_limit(current_user.username)

    # ── 1. Fetch topology relationships ───────────────────────────────
    try:
        if entity_type:
            # When an entity_type filter is provided, restrict to relationships
            # where at least one endpoint matches that type.
            rel_query = text("""
                SELECT id, from_entity_id, from_entity_type,
                       to_entity_id, to_entity_type, relationship_type,
                       properties, created_at
                FROM topology_relationships
                WHERE tenant_id = :tid
                  AND (from_entity_type = :etype OR to_entity_type = :etype)
                LIMIT :lim
            """)
            result = await db.execute(
                rel_query, {"tid": tenant_id, "etype": entity_type, "lim": limit}
            )
        else:
            rel_query = text("""
                SELECT id, from_entity_id, from_entity_type,
                       to_entity_id, to_entity_type, relationship_type,
                       properties, created_at
                FROM topology_relationships
                WHERE tenant_id = :tid
                LIMIT :lim
            """)
            result = await db.execute(rel_query, {"tid": tenant_id, "lim": limit})
        rows = result.fetchall()
    except Exception as e:
        logger.warning(f"Topology query failed: {e}")
        rows = []

    # ── 2. Collect unique entity IDs referenced by relationships ──────
    entity_ids_set: set[str] = set()
    relationships = []
    for row in rows:
        rel_id, from_id, from_type, to_id, to_type, rel_type, props, created_at = row
        entity_ids_set.add(str(from_id))
        entity_ids_set.add(str(to_id))
        relationships.append(
            {
                "id": str(rel_id),
                "source_entity_id": str(from_id),
                "target_entity_id": str(to_id),
                "relationship_type": rel_type,
                "properties": None,
            }
        )

    # ── 3. Bulk-resolve entity names from network_entities ────────────
    # This replaces the old approach of using the UUID as the name.
    entity_details: dict[str, dict] = {}
    if entity_ids_set:
        try:
            # Convert set to a list for the ANY(:ids) bind parameter.
            ids_list = list(entity_ids_set)
            name_result = await db.execute(
                text("""
                    SELECT id::text, name, external_id, entity_type,
                           operational_status
                    FROM network_entities
                    WHERE tenant_id = :tid
                      AND id::text = ANY(:ids)
                """),
                {"tid": tenant_id, "ids": ids_list},
            )
            for eid, name, ext_id, etype, op_status in name_result.fetchall():
                entity_details[str(eid)] = {
                    "name": name,
                    "external_id": ext_id or str(eid),
                    "entity_type": etype,
                    "status": op_status or "unknown",
                }
        except Exception as e:
            logger.warning(f"Entity name resolution failed: {e}")

    # ── 4. Build entity response list ─────────────────────────────────
    # For every entity ID referenced by a relationship, produce an
    # EntityResponse with a resolved name when available.
    entity_map: dict[str, dict] = {}
    for row in rows:
        _rel_id, from_id, from_type, to_id, to_type, *_ = row
        for eid, etype in [(str(from_id), from_type), (str(to_id), to_type)]:
            if eid in entity_map:
                continue
            details = entity_details.get(eid)
            if details:
                entity_map[eid] = {
                    "id": eid,
                    "external_id": details["external_id"],
                    "name": details["name"],
                    "entity_type": details["entity_type"],
                    "tenant_id": tenant_id,
                    "properties": {"status": details["status"]},
                }
            else:
                # Fallback — entity not in network_entities (rare)
                short_id = eid[:8] if len(eid) > 8 else eid
                entity_map[eid] = {
                    "id": eid,
                    "external_id": eid,
                    "name": f"{etype or 'UNKNOWN'}-{short_id}",
                    "entity_type": etype or "UNKNOWN",
                    "tenant_id": tenant_id,
                }

    entities = [EntityResponse(**e) for e in entity_map.values()]
    rels = [RelationshipResponse(**r) for r in relationships]

    # ── 5. Topology health summary ────────────────────────────────────
    # Get total entity count for the tenant (cheap COUNT)
    try:
        total_result = await db.execute(
            text("SELECT COUNT(*) FROM network_entities WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        total_entity_count = total_result.scalar() or 0
    except Exception:
        total_entity_count = len(entities)

    health = TopologyHealth(
        total_entities=total_entity_count,
        stale_entities=0,
        completeness_pct=round(len(entities) / total_entity_count * 100, 1)
        if total_entity_count > 0
        else 0.0,
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

    # Resolve entity's own name
    entity_name = entity_id
    entity_type = "unknown"
    try:
        ent_row = await db.execute(
            text("""
                SELECT name, entity_type, external_id, operational_status
                FROM network_entities
                WHERE id::text = :eid AND tenant_id = :tid
            """),
            {"eid": entity_id, "tid": tenant_id},
        )
        ent = ent_row.fetchone()
        if ent:
            entity_name = ent[0]
            entity_type = ent[1]
    except Exception as e:
        logger.warning(f"Entity name lookup failed: {e}")

    try:
        # Strict tenant isolation in entity query (Finding S-1 Fix)
        result = await db.execute(
            text("""
                SELECT id, from_entity_id, from_entity_type, to_entity_id, to_entity_type, relationship_type
                FROM topology_relationships
                WHERE (from_entity_id = :eid OR to_entity_id = :eid)
                AND tenant_id = :tid
                LIMIT 200
            """),
            {"eid": entity_id, "tid": tenant_id},
        )
        rows = result.fetchall()
    except Exception as e:
        logger.warning(f"Entity query failed: {e}")
        rows = []

    # Collect neighbour IDs for bulk name resolution
    neighbour_ids: set[str] = set()
    raw_neighbours = []
    for row in rows:
        _, from_id, from_type, to_id, to_type, rel_type = row
        neighbour_id = str(to_id) if str(from_id) == entity_id else str(from_id)
        neighbour_type = to_type if str(from_id) == entity_id else from_type
        neighbour_ids.add(neighbour_id)
        raw_neighbours.append((neighbour_id, neighbour_type, rel_type))

    # Bulk-resolve neighbour names
    name_map: dict[str, str] = {}
    if neighbour_ids:
        try:
            nr = await db.execute(
                text("""
                    SELECT id::text, name FROM network_entities
                    WHERE tenant_id = :tid AND id::text = ANY(:ids)
                """),
                {"tid": tenant_id, "ids": list(neighbour_ids)},
            )
            for nid, nname in nr.fetchall():
                name_map[str(nid)] = nname
        except Exception:
            pass

    neighbours = []
    for nid, ntype, rtype in raw_neighbours:
        neighbours.append(
            {
                "entity_id": nid,
                "entity_name": name_map.get(nid, nid[:12]),
                "entity_type": ntype,
                "relationship_type": rtype,
            }
        )

    return {
        "entity_id": entity_id,
        "entity_name": entity_name,
        "entity_type": entity_type,
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

    # Pre-load a name cache for entities we encounter during traversal.
    # Populated lazily; avoids one query per node.
    _name_cache: dict[str, tuple[str, str, str]] = {}  # eid -> (name, type, ext_id)

    async def _resolve_name(eid: str) -> tuple[str, str, str]:
        """Return (name, entity_type, external_id) for *eid*."""
        if eid in _name_cache:
            return _name_cache[eid]
        try:
            r = await db.execute(
                text(
                    "SELECT name, entity_type, external_id FROM network_entities WHERE id::text = :eid AND tenant_id = :tid"
                ),
                {"eid": eid, "tid": tenant_id},
            )
            row = r.fetchone()
            if row:
                _name_cache[eid] = (row[0], row[1], row[2] or eid)
                return _name_cache[eid]
        except Exception:
            pass
        short = eid[:12] if len(eid) > 12 else eid
        _name_cache[eid] = (short, "UNKNOWN", eid)
        return _name_cache[eid]

    async def get_neighbours_recursive(
        eid: str, depth: int, direction: str, visited: set
    ) -> List[ImpactTreeNode]:
        if depth > max_hops or eid in visited:
            return []
        visited.add(eid)

        nodes: List[ImpactTreeNode] = []
        if direction == "upstream":
            q = text(
                "SELECT from_entity_id, from_entity_type, relationship_type FROM topology_relationships WHERE to_entity_id = :eid AND tenant_id = :tid LIMIT 50"
            )
        else:
            q = text(
                "SELECT to_entity_id, to_entity_type, relationship_type FROM topology_relationships WHERE from_entity_id = :eid AND tenant_id = :tid LIMIT 50"
            )

        res = await db.execute(q, {"eid": eid, "tid": tenant_id})
        rows = res.fetchall()
        logger.info(
            f"Impact recursive {eid} {direction} depth {depth} found {len(rows)} rows for tenant {tenant_id}"
        )

        for next_id, next_type, rel_type in rows:
            nid = str(next_id)
            name, etype, ext_id = await _resolve_name(nid)
            node = ImpactTreeNode(
                entity_id=nid,
                entity_name=name,
                entity_type=etype,
                external_id=ext_id,
                direction=direction,
                relationship_type=rel_type,
                depth=depth,
            )
            nodes.append(node)
            nodes.extend(
                await get_neighbours_recursive(nid, depth + 1, direction, visited)
            )

        return nodes

    # Resolve root entity name
    root_name, root_type, root_ext = await _resolve_name(entity_id)

    upstream = await get_neighbours_recursive(entity_id, 1, "upstream", set())
    downstream = await get_neighbours_recursive(entity_id, 1, "downstream", set())

    return ImpactTreeResponse(
        root_entity_id=entity_id,
        root_entity_name=root_name,
        root_entity_type=root_type,
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
            {"tid": tenant_id},
        )
        total = total_res.scalar() or 0

        # Stale = records older than 7 days (using last_synced_at if present, else created_at)
        stale_res = await db.execute(
            text("""
                SELECT COUNT(*) FROM topology_relationships
                WHERE tenant_id = :tid
                AND (last_synced_at IS NULL OR last_synced_at < :threshold)
            """),
            {"tid": tenant_id, "threshold": staleness_threshold},
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
        completeness_pct=round(max(0, (total - stale) / total * 100), 1)
        if total > 0
        else 0.0,
        staleness_threshold_days=7,
    )


@router.get("/{tenant_id}/search")
async def search_entities(
    tenant_id: str,
    q: str = Query(..., min_length=2, description="Search term (name, external_id, or entity_type)"),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[TOPOLOGY_READ]),
):
    """
    Search for entities in the CMDB. Used to find a seed node for topology exploration.
    """
    search_term = f"%{q}%"
    try:
        result = await db.execute(
            text("""
                SELECT id, name, entity_type, external_id, operational_status
                FROM network_entities
                WHERE tenant_id = :tid
                  AND (name LIKE :q OR external_id LIKE :q OR entity_type LIKE :q)
                LIMIT :limit
            """),
            {"tid": tenant_id, "q": search_term, "limit": limit},
        )
        rows = result.fetchall()
        
        entities = []
        for r in rows:
            entities.append({
                "id": str(r[0]),
                "name": r[1],
                "entity_type": r[2],
                "external_id": r[3],
                "status": r[4] or "unknown",
            })
            
        return {"tenant_id": tenant_id, "query": q, "results": entities}
    except Exception as e:
        logger.error(f"Topology search failed: {e}")
        raise HTTPException(status_code=500, detail="Search failed")


@router.get("/{tenant_id}/neighborhood/{entity_id}")
async def get_neighborhood(
    tenant_id: str,
    entity_id: str,
    hops: int = Query(2, ge=1, le=5, description="Number of hops to traverse"),
    max_nodes: int = Query(300, ge=10, le=1000, description="Safety limit for explosive graphs"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[TOPOLOGY_READ]),
):
    """
    Get an N-hop neighborhood graph around a specific seed entity.
    Returns nodes and edges formatted for the frontend canvas.
    """
    # 1. Start with the seed
    visited_nodes: set[str] = {entity_id}
    all_edges: set[tuple[str, str, str]] = set()  # (from_id, to_id, rel_type)
    
    current_frontier: set[str] = {entity_id}
    
    # Breadth-first traversal up to N hops
    for hop in range(hops):
        if not current_frontier or len(visited_nodes) >= max_nodes:
            break
            
        # Get edges where current frontier is source OR target
        # Using string binding for the IN clause
        frontier_list = list(current_frontier)
        
        try:
            from sqlalchemy import bindparam
            result = await db.execute(
                text("""
                    SELECT from_entity_id, to_entity_id, relationship_type
                    FROM topology_relationships
                    WHERE tenant_id = :tid 
                      AND (from_entity_id IN :frontier OR to_entity_id IN :frontier)
                """).bindparams(bindparam("frontier", expanding=True)),
                {"tid": tenant_id, "frontier": frontier_list}
            )
            rows = result.fetchall()
            
            next_frontier: set[str] = set()
            for r in rows:
                f_id, t_id, r_type = str(r[0]), str(r[1]), r[2]
                all_edges.add((f_id, t_id, r_type))
                
                if f_id not in visited_nodes and len(visited_nodes) < max_nodes:
                    visited_nodes.add(f_id)
                    next_frontier.add(f_id)
                if t_id not in visited_nodes and len(visited_nodes) < max_nodes:
                    visited_nodes.add(t_id)
                    next_frontier.add(t_id)
                    
            current_frontier = next_frontier
            
        except Exception as e:
            logger.error(f"Neighborhood traversal hop {hop} failed: {e}")
            break

    # 2. Resolve entity names for all visited nodes
    entities = []
    if visited_nodes:
        try:
            from sqlalchemy import bindparam
            name_result = await db.execute(
                text("""
                    SELECT id, name, entity_type, external_id, operational_status,
                           latitude, longitude
                    FROM network_entities
                    WHERE tenant_id = :tid AND id IN :ids
                """).bindparams(bindparam("ids", expanding=True)),
                {"tid": tenant_id, "ids": list(visited_nodes)}
            )
            
            resolved_ids = set()
            for r in name_result.fetchall():
                eid = str(r[0])
                resolved_ids.add(eid)
                entities.append({
                    "id": eid,
                    "name": r[1],
                    "entity_type": r[2],
                    "external_id": r[3] or eid,
                    "status": r[4] or "unknown",
                    "geo_lat": float(r[5]) if r[5] is not None else None,
                    "geo_lon": float(r[6]) if r[6] is not None else None,
                    "properties": {"status": r[4] or "unknown"}
                })
                
            # Add fallbacks for nodes in relationships but missing from entities table
            for missing_id in visited_nodes - resolved_ids:
                short = missing_id[:8] if len(missing_id) > 8 else missing_id
                entities.append({
                    "id": missing_id,
                    "name": f"UNKNOWN-{short}",
                    "entity_type": "UNKNOWN",
                    "external_id": missing_id,
                    "status": "unknown",
                    "geo_lat": None,
                    "geo_lon": None,
                    "properties": {"status": "unknown"}
                })
                
        except Exception as e:
            logger.error(f"Entity resolution failed: {e}")

    # Format edges
    edges = [
        {
            "id": f"{f}-{t}-{r}",
            "source_entity_id": f,
            "target_entity_id": t,
            "relationship_type": r
        }
        for f, t, r in all_edges
    ]

    return {
        "tenant_id": tenant_id,
        "seed_id": entity_id,
        "hops": hops,
        "nodes_returned": len(entities),
        "edges_returned": len(edges),
        "entities": entities,
        "relationships": edges
    }


@router.get("/{tenant_id}/neighborhood-with-shadow/{entity_id}")
async def get_neighborhood_with_shadow(
    tenant_id: str,
    entity_id: str,
    hops: int = Query(2, ge=1, le=5),
    max_nodes: int = Query(300, ge=10, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[TOPOLOGY_READ]),
):
    """
    Get N-hop neighborhood including shadow (inferred) topology links.
    Shadow links are marked with source='inferred' for visual distinction.
    """
    # Get regular neighborhood first
    regular = await get_neighborhood(
        tenant_id=tenant_id,
        entity_id=entity_id,
        hops=hops,
        max_nodes=max_nodes,
        db=db,
        current_user=current_user,
    )

    # Now find shadow relationships connected to any entity in the regular neighborhood
    entity_ids = [e["id"] for e in regular.get("entities", [])]
    if not entity_ids:
        regular["shadow_entities"] = []
        regular["shadow_relationships"] = []
        return regular

    try:
        # Find shadow entities that match our entity identifiers
        from sqlalchemy import bindparam
        shadow_rels = await db.execute(
            text("""
                SELECT sr.id, sr.from_entity_id, sr.to_entity_id,
                       sr.relationship_type, sr.confidence,
                       se_from.entity_identifier AS from_identifier,
                       se_to.entity_identifier AS to_identifier,
                       se_from.entity_domain AS from_domain,
                       se_to.entity_domain AS to_domain
                FROM shadow_relationship sr
                JOIN shadow_entity se_from ON sr.from_entity_id = se_from.id AND se_from.tenant_id = :tid
                JOIN shadow_entity se_to ON sr.to_entity_id = se_to.id AND se_to.tenant_id = :tid
                WHERE sr.tenant_id = :tid
                  AND (se_from.entity_identifier IN :ids OR se_to.entity_identifier IN :ids)
                  AND sr.exported_to_cmdb = false
                LIMIT 200
            """).bindparams(bindparam("ids", expanding=True)),
            {"tid": tenant_id, "ids": entity_ids},
        )

        shadow_edges = []
        shadow_node_ids = set()
        for r in shadow_rels.fetchall():
            shadow_edges.append({
                "id": f"shadow-{r[0]}",
                "source_entity_id": r[5],  # from_identifier
                "target_entity_id": r[6],  # to_identifier
                "relationship_type": r[3],
                "source": "inferred",
                "confidence": float(r[4]) if r[4] else None,
            })
            # Track shadow-only nodes (not already in CMDB view)
            if r[5] not in entity_ids:
                shadow_node_ids.add(r[5])
            if r[6] not in entity_ids:
                shadow_node_ids.add(r[6])

        # Resolve shadow-only nodes
        shadow_entities = []
        if shadow_node_ids:
            for sid in shadow_node_ids:
                se_row = await db.execute(
                    text("""
                        SELECT entity_identifier, entity_domain, enrichment_value, origin
                        FROM shadow_entity
                        WHERE tenant_id = :tid AND entity_identifier = :ident
                    """),
                    {"tid": tenant_id, "ident": sid},
                )
                se = se_row.fetchone()
                if se:
                    shadow_entities.append({
                        "id": se[0],
                        "name": f"[Inferred] {se[0][:20]}",
                        "entity_type": "INFERRED",
                        "external_id": se[0],
                        "status": "inferred",
                        "source": "shadow_topology",
                        "domain": se[1],
                        "confidence": float(se[2]) if se[2] else None,
                        "origin": se[3],
                        "properties": {"status": "inferred"},
                    })

        regular["shadow_entities"] = shadow_entities
        regular["shadow_relationships"] = shadow_edges

    except Exception as e:
        logger.warning(f"Shadow topology lookup failed: {e}")
        regular["shadow_entities"] = []
        regular["shadow_relationships"] = []

    return regular

