-- Migration: Add missing columns to network_entities table
-- Required by NetworkEntityORM (item #6 from TELCO2_IMPLEMENTATION_BRIEF.md)
--
-- The Telco2 bulk-loaded data has: id, tenant_id, entity_type, name, external_id,
-- latitude, longitude, operational_status, created_at, updated_at, attributes.
--
-- The ORM also references: revenue_weight, sla_tier, embedding_provider,
-- embedding_model, last_seen_at — these do NOT exist in the DB yet.
-- This script adds them so SQLAlchemy queries don't crash with
-- "column does not exist" errors.
--
-- Safe to run multiple times (IF NOT EXISTS).
--
-- Usage:
--   psql -h localhost -p 5432 -U postgres -d pedkai -f backend/app/scripts/alter_network_entities.sql

ALTER TABLE network_entities ADD COLUMN IF NOT EXISTS revenue_weight DOUBLE PRECISION;
ALTER TABLE network_entities ADD COLUMN IF NOT EXISTS sla_tier VARCHAR(50);
ALTER TABLE network_entities ADD COLUMN IF NOT EXISTS embedding_provider VARCHAR(50);
ALTER TABLE network_entities ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(100);
ALTER TABLE network_entities ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP;
