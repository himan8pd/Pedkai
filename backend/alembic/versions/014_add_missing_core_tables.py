"""Add missing core tables to Alembic history

Revision ID: 014_add_missing_core_tables
Revises: 013_counterflag
Create Date: 2026-03-18 18:56:00.000000

Adds four production tables that existed in the database before Alembic
history tracking was established:
  - telco_events_alarms   (events_alarms.parquet target)
  - neighbour_relations   (neighbour_relations.parquet target)
  - vendor_naming_map     (vendor_naming_map.parquet target)
  - kpi_dataset_registry  (KPI dataset metadata registry)

All operations use CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS
so they are safe to run against a database that already has these tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '014_add_missing_core_tables'
down_revision: Union[str, Sequence[str], None] = '013_counterflag'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. telco_events_alarms
    #    Target for events_alarms.parquet.
    #    alarm_id is the natural PK from the generator (UUID v4).
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS telco_events_alarms (
            alarm_id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               VARCHAR(100) NOT NULL,
            entity_id               UUID,
            entity_type             VARCHAR(100),
            alarm_type              VARCHAR(100) NOT NULL,
            severity                VARCHAR(20)  NOT NULL,
            raised_at               TIMESTAMP WITH TIME ZONE NOT NULL,
            cleared_at              TIMESTAMP WITH TIME ZONE,
            source_system           VARCHAR(100) NOT NULL,
            probable_cause          TEXT,
            domain                  VARCHAR(50)  NOT NULL,
            scenario_id             VARCHAR(255),
            is_synthetic_scenario   BOOLEAN NOT NULL DEFAULT FALSE,
            additional_text         TEXT,
            correlation_group_id    UUID
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_tea_tenant_raised ON telco_events_alarms (tenant_id, raised_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tea_tenant_entity ON telco_events_alarms (tenant_id, entity_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tea_tenant_type   ON telco_events_alarms (tenant_id, alarm_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tea_tenant_domain ON telco_events_alarms (tenant_id, domain)")

    # ------------------------------------------------------------------
    # 2. neighbour_relations
    #    Target for neighbour_relations.parquet.
    #    relation_id is the natural UUID PK from the generator.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS neighbour_relations (
            relation_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               VARCHAR(100) NOT NULL,
            from_cell_id            UUID NOT NULL,
            from_cell_rat           VARCHAR(20)  NOT NULL,
            from_cell_band          VARCHAR(50)  NOT NULL,
            to_cell_id              UUID NOT NULL,
            to_cell_rat             VARCHAR(20)  NOT NULL,
            to_cell_band            VARCHAR(50)  NOT NULL,
            neighbour_type          VARCHAR(50)  NOT NULL,
            is_intra_site           BOOLEAN NOT NULL DEFAULT FALSE,
            distance_m              DOUBLE PRECISION,
            handover_attempts       DOUBLE PRECISION NOT NULL DEFAULT 0,
            handover_success_rate   DOUBLE PRECISION NOT NULL DEFAULT 0,
            cio_offset_db           DOUBLE PRECISION NOT NULL DEFAULT 0,
            no_remove_flag          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_nr_tenant           ON neighbour_relations (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_nr_tenant_from      ON neighbour_relations (tenant_id, from_cell_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_nr_tenant_to        ON neighbour_relations (tenant_id, to_cell_id)")

    # ------------------------------------------------------------------
    # 3. vendor_naming_map
    #    Target for vendor_naming_map.parquet.
    #    mapping_id is the natural UUID PK from the generator.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS vendor_naming_map (
            mapping_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           VARCHAR(100) NOT NULL,
            internal_name       VARCHAR(255) NOT NULL,
            domain              VARCHAR(50),
            vendor              VARCHAR(50),
            vendor_counter_name VARCHAR(255),
            vendor_system       VARCHAR(100),
            unit                VARCHAR(50),
            description         TEXT,
            counter_family      VARCHAR(100),
            three_gpp_ref       VARCHAR(100)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_vnm_tenant          ON vendor_naming_map (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_vnm_internal_name   ON vendor_naming_map (tenant_id, internal_name)")

    # ------------------------------------------------------------------
    # 4. kpi_dataset_registry
    #    Metadata registry for external KPI Parquet files.
    #    Natural PK is (dataset_name, tenant_id).
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS kpi_dataset_registry (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            dataset_name    VARCHAR(100) NOT NULL,
            tenant_id       VARCHAR(100) NOT NULL,
            file_path       TEXT,
            total_rows      BIGINT NOT NULL DEFAULT 0,
            total_columns   INTEGER NOT NULL DEFAULT 0,
            file_size_bytes BIGINT NOT NULL DEFAULT 0,
            schema_json     JSONB,
            registered_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            UNIQUE (dataset_name, tenant_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_kdr_tenant ON kpi_dataset_registry (tenant_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS kpi_dataset_registry CASCADE")
    op.execute("DROP TABLE IF EXISTS vendor_naming_map CASCADE")
    op.execute("DROP TABLE IF EXISTS neighbour_relations CASCADE")
    op.execute("DROP TABLE IF EXISTS telco_events_alarms CASCADE")
