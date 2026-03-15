"""Abeyance Memory subsystem tables

Revision ID: 010_abeyance_memory_subsystem
Revises: 009_create_customers_tables
Create Date: 2026-03-15 00:00:00.000000

Creates the full Abeyance Memory schema as specified in
docs/ABEYANCE_MEMORY_LLD.md §14.

Tables:
- abeyance_fragment        — core fragment store (LLD §5)
- fragment_entity_ref      — fragment-to-entity junction (LLD §5)
- accumulation_edge        — weak affinity links (LLD §10)
- shadow_entity            — private topology node (LLD §8)
- shadow_relationship      — private topology edge (LLD §8)
- cmdb_export_log          — export audit trail (LLD §8)
- discovery_ledger         — value attribution record (LLD §13)
- value_event              — value realization events (LLD §13)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '010_abeyance_memory_subsystem'
down_revision: Union[str, Sequence[str], None] = '009_create_customers_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create Abeyance Memory tables (idempotent)."""

    # Ensure pgvector extension is available
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # -- abeyance_fragment (LLD §5 Fragment Model) --------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS abeyance_fragment (
            id                          UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id                   VARCHAR(100) NOT NULL,
            source_type                 VARCHAR(50) NOT NULL,
            raw_content                 TEXT,
            extracted_entities          JSONB       DEFAULT '[]'::jsonb,
            topological_neighbourhood   JSONB       DEFAULT '{}'::jsonb,
            operational_fingerprint     JSONB       DEFAULT '{}'::jsonb,
            failure_mode_tags           JSONB       DEFAULT '[]'::jsonb,
            temporal_context            JSONB       DEFAULT '{}'::jsonb,
            enriched_embedding          vector(1536),
            raw_embedding               vector(768),
            event_timestamp             TIMESTAMP WITH TIME ZONE,
            ingestion_timestamp         TIMESTAMP WITH TIME ZONE DEFAULT now(),
            base_relevance              FLOAT       NOT NULL DEFAULT 1.0,
            current_decay_score         FLOAT       NOT NULL DEFAULT 1.0,
            near_miss_count             INTEGER     NOT NULL DEFAULT 0,
            snap_status                 VARCHAR(20) NOT NULL DEFAULT 'ABEYANCE',
            snapped_hypothesis_id       UUID,
            source_ref                  VARCHAR(500),
            source_engineer_id          VARCHAR(255),
            created_at                  TIMESTAMP WITH TIME ZONE DEFAULT now(),
            updated_at                  TIMESTAMP WITH TIME ZONE,
            PRIMARY KEY (id)
        )
    """)

    # Indexes for abeyance_fragment (LLD §14)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_abeyance_fragment_tenant_id "
        "ON abeyance_fragment (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_abeyance_fragment_tenant_status "
        "ON abeyance_fragment (tenant_id, snap_status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_abeyance_fragment_decay "
        "ON abeyance_fragment (current_decay_score) "
        "WHERE snap_status = 'ABEYANCE'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_abeyance_fragment_failure_modes "
        "ON abeyance_fragment USING GIN (failure_mode_tags jsonb_path_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_abeyance_fragment_entities "
        "ON abeyance_fragment USING GIN (extracted_entities jsonb_path_ops)"
    )

    # -- fragment_entity_ref (LLD §5 entity junction) -----------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS fragment_entity_ref (
            id                  UUID        NOT NULL DEFAULT gen_random_uuid(),
            fragment_id         UUID        NOT NULL REFERENCES abeyance_fragment(id) ON DELETE CASCADE,
            entity_id           UUID,
            entity_identifier   VARCHAR(500) NOT NULL,
            entity_domain       VARCHAR(50),
            topological_distance INTEGER    NOT NULL DEFAULT 0,
            tenant_id           VARCHAR(100) NOT NULL,
            PRIMARY KEY (id)
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fer_fragment_id "
        "ON fragment_entity_ref (fragment_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fer_entity_id "
        "ON fragment_entity_ref (entity_id, fragment_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fer_entity_identifier "
        "ON fragment_entity_ref (entity_identifier, tenant_id)"
    )

    # -- accumulation_edge (LLD §10 Accumulation Graph) ---------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS accumulation_edge (
            id                      UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               VARCHAR(100) NOT NULL,
            fragment_a_id           UUID        NOT NULL REFERENCES abeyance_fragment(id),
            fragment_b_id           UUID        NOT NULL REFERENCES abeyance_fragment(id),
            affinity_score          FLOAT       NOT NULL,
            strongest_failure_mode  VARCHAR(50),
            created_at              TIMESTAMP WITH TIME ZONE DEFAULT now(),
            last_updated            TIMESTAMP WITH TIME ZONE DEFAULT now(),
            PRIMARY KEY (id)
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_accum_edge_fragment_a "
        "ON accumulation_edge (fragment_a_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_accum_edge_fragment_b "
        "ON accumulation_edge (fragment_b_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_accum_edge_pair "
        "ON accumulation_edge (fragment_a_id, fragment_b_id)"
    )

    # -- shadow_entity (LLD §8 Shadow Topology) ----------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS shadow_entity (
            id                      UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               VARCHAR(100) NOT NULL,
            entity_identifier       VARCHAR(500) NOT NULL,
            entity_domain           VARCHAR(50),
            origin                  VARCHAR(30) NOT NULL DEFAULT 'CMDB_DECLARED',
            discovery_hypothesis_id UUID,
            first_seen              TIMESTAMP WITH TIME ZONE DEFAULT now(),
            last_evidence           TIMESTAMP WITH TIME ZONE DEFAULT now(),
            attributes              JSONB       DEFAULT '{}'::jsonb,
            cmdb_attributes         JSONB       DEFAULT '{}'::jsonb,
            enrichment_value        FLOAT       NOT NULL DEFAULT 0.0,
            PRIMARY KEY (id)
        )
    """)

    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_shadow_entity_tenant_identifier "
        "ON shadow_entity (tenant_id, entity_identifier)"
    )

    # -- shadow_relationship (LLD §8 Shadow Topology) ----------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS shadow_relationship (
            id                      UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               VARCHAR(100) NOT NULL,
            from_entity_id          UUID        NOT NULL REFERENCES shadow_entity(id),
            to_entity_id            UUID        NOT NULL REFERENCES shadow_entity(id),
            relationship_type       VARCHAR(50) NOT NULL,
            origin                  VARCHAR(30) NOT NULL DEFAULT 'CMDB_DECLARED',
            discovery_hypothesis_id UUID,
            confidence              FLOAT       NOT NULL DEFAULT 1.0,
            discovered_at           TIMESTAMP WITH TIME ZONE DEFAULT now(),
            evidence_summary        JSONB       DEFAULT '{}'::jsonb,
            exported_to_cmdb        BOOLEAN     NOT NULL DEFAULT FALSE,
            exported_at             TIMESTAMP WITH TIME ZONE,
            cmdb_reference_tag      VARCHAR(255),
            PRIMARY KEY (id)
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_shadow_rel_from "
        "ON shadow_relationship (from_entity_id, tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_shadow_rel_to "
        "ON shadow_relationship (to_entity_id, tenant_id)"
    )

    # -- cmdb_export_log (LLD §8) ------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS cmdb_export_log (
            id                  UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           VARCHAR(100) NOT NULL,
            relationship_id     UUID        REFERENCES shadow_relationship(id),
            entity_id           UUID        REFERENCES shadow_entity(id),
            export_type         VARCHAR(30) NOT NULL,
            exported_at         TIMESTAMP WITH TIME ZONE DEFAULT now(),
            exported_payload    JSONB       DEFAULT '{}'::jsonb,
            retained_payload    JSONB       DEFAULT '{}'::jsonb,
            cmdb_reference_tag  VARCHAR(255),
            PRIMARY KEY (id)
        )
    """)

    # -- discovery_ledger (LLD §13 Value Attribution) -----------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS discovery_ledger (
            id                      UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               VARCHAR(100) NOT NULL,
            hypothesis_id           UUID,
            discovery_type          VARCHAR(50) NOT NULL,
            discovered_entities     JSONB       DEFAULT '[]'::jsonb,
            discovered_relationships JSONB      DEFAULT '[]'::jsonb,
            cmdb_reference_tag      VARCHAR(255),
            discovered_at           TIMESTAMP WITH TIME ZONE DEFAULT now(),
            cmdb_exported_at        TIMESTAMP WITH TIME ZONE,
            discovery_confidence    FLOAT       NOT NULL DEFAULT 0.0,
            status                  VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
            PRIMARY KEY (id)
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_discovery_ledger_tenant "
        "ON discovery_ledger (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_discovery_entities "
        "ON discovery_ledger USING GIN (discovered_entities jsonb_path_ops)"
    )

    # -- value_event (LLD §13 Value Attribution) ----------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS value_event (
            id                          UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id                   VARCHAR(100) NOT NULL,
            ledger_entry_id             UUID        NOT NULL REFERENCES discovery_ledger(id),
            event_type                  VARCHAR(50) NOT NULL,
            event_at                    TIMESTAMP WITH TIME ZONE DEFAULT now(),
            event_detail                JSONB       DEFAULT '{}'::jsonb,
            attributed_value_hours      FLOAT,
            attributed_value_currency   FLOAT,
            attribution_rationale       TEXT,
            PRIMARY KEY (id)
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_value_event_ledger "
        "ON value_event (ledger_entry_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_value_event_tenant "
        "ON value_event (tenant_id)"
    )


def downgrade() -> None:
    """Drop all Abeyance Memory tables in reverse dependency order."""
    op.execute("DROP TABLE IF EXISTS value_event")
    op.execute("DROP TABLE IF EXISTS discovery_ledger")
    op.execute("DROP TABLE IF EXISTS cmdb_export_log")
    op.execute("DROP TABLE IF EXISTS shadow_relationship")
    op.execute("DROP TABLE IF EXISTS shadow_entity")
    op.execute("DROP TABLE IF EXISTS accumulation_edge")
    op.execute("DROP TABLE IF EXISTS fragment_entity_ref")
    op.execute("DROP TABLE IF EXISTS abeyance_fragment")
