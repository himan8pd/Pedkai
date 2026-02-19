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
