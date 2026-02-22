# ADR: Data Architecture - Retention, Backup, and DR

## Status
Approved

## Context
Pedkai requires a highly resilient data layer to handle high-velocity TMF628 KPI streams and critical incident audit trails. The system must support data sovereignty and rapid recovery in case of regional failure.

## Decision

### 1. Storage Engine
- **Primary Database**: PostgreSQL 15.
- **Time-Series extension**: TimescaleDB for efficient storage and querying of KPI metrics.

### 2. Multi-Tenancy
- **Strategy**: Row-level security (RLS) and mandatory `tenant_id` columns on all critical tables.
- **Isolation**: Shared database instances but logical isolation at the query layer.

### 3. Backup & Recovery
- **Frequency**: Automated daily full snapshots.
- **Transaction Logs**: Write-Ahead Logging (WAL) archived every 5 minutes to object storage (S3/GCS).
- **Point-in-Time Recovery (PITR)**: Support for recovery to any second within the last 14 days.

### 4. Disaster Recovery (DR)
- **DR Target**: Cross-region replication of backups.
- **RTO (Recovery Time Objective)**: < 4 hours.
- **RPO (Recovery Point Objective)**: < 15 minutes.

### 5. Data Sovereignty
- Data remains within the tenant's specified geographical region.
- Egress is blocked by default; only anonymized metrics allowed to the central dashboard.

---

### 6. Topology Data Refresh Strategy

Topology data (network entities and their relationships) is refreshed via the following mechanism:

**Source**: OSS systems (Ericsson ENM, Nokia NetAct) publish topology change events to a Kafka topic: `topology.updates`

**Processing**:
1. Pedkai's topology consumer reads from `topology.updates`
2. Each consumed event UPSERTs network entities and topology relationships
3. `last_synced_at` is updated on every `topology_relationships` record touched by the sync
4. Stale detection threshold: **7 days** (configurable via `TOPOLOGY_STALENESS_DAYS` env var)

**Staleness alerting**:
```sql
SELECT COUNT(*) FROM topology_relationships
WHERE tenant_id = :tid
AND (last_synced_at IS NULL OR last_synced_at < NOW() - INTERVAL '7 days')
```
If count > 0, a NOC dashboard alert is raised: `"Topology data is stale — OSS sync may be degraded"`.

**Why not `created_at`**: Topology relationships rarely change. Using `created_at < yesterday` generates false-positive staleness alerts. `last_synced_at` correctly reflects when the relationship was last confirmed by the OSS.

---

### 7. Graph Scalability

**Current approach**: PostgreSQL recursive CTEs with depth limit of 5 hops and row limit of 1,000.

- Supports: up to ~10,000 network entities per tenant
- Limitation: CTE performance degrades beyond ~50,000 relationships

**Migration path for larger networks**:

| Scale | Recommended approach |
|-------|---------------------|
| < 10K entities | PostgreSQL recursive CTE (current) |
| 10K – 100K entities | Apache AGE (PostgreSQL graph extension) — no schema migration required |
| > 100K entities | Neo4j — requires ETL pipeline from PostgreSQL to Neo4j |

When migrating to Neo4j:
1. Deploy Neo4j alongside PostgreSQL
2. Replicate `topology_relationships` to Neo4j via Kafka Connect
3. Migrate `cx_intelligence.py` CTE queries to Cypher queries
4. PostgreSQL remains the system of record; Neo4j is read-only replica for graph queries

The decision to migrate should be triggered when recursive CTE queries exceed p95 > 200ms on a 30-day rolling average.
