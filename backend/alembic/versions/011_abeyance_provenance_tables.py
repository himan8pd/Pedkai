"""Add provenance tables, new columns, and remediated indexes

Revision ID: 011_abeyance_provenance_tables
Revises: 010_abeyance_memory_subsystem
Create Date: 2026-03-15 12:00:00.000000

Adds tables and columns required by the Forensic Audit remediation:
- fragment_history          — append-only fragment state change log (INV-10)
- snap_decision_record      — persisted snap evaluation records (Audit §7.1)
- cluster_snapshot           — cluster evaluation snapshots (Audit §7.3)
- abeyance_fragment columns: embedding_mask, dedup_key, max_lifetime_days
- Default snap_status changed: ABEYANCE → INGESTED
- accumulation_edge: tenant-scoped uniqueness (Audit §9.2)
- Additional tenant-scoped indexes on all tables
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '011_abeyance_provenance_tables'
down_revision: Union[str, Sequence[str], None] = '010_abeyance_memory_subsystem'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add provenance tables and remediation columns."""

    # -- fragment_history (INV-10: append-only) --------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS fragment_history (
            id                  UUID        NOT NULL DEFAULT gen_random_uuid(),
            fragment_id         UUID        NOT NULL,
            tenant_id           VARCHAR(100) NOT NULL,
            event_type          VARCHAR(30) NOT NULL,
            event_timestamp     TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            old_state           JSONB,
            new_state           JSONB,
            event_detail        JSONB,
            PRIMARY KEY (id)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fh_fragment_time "
        "ON fragment_history (fragment_id, event_timestamp)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fh_tenant_time "
        "ON fragment_history (tenant_id, event_timestamp)"
    )

    # -- snap_decision_record (Audit §7.1) ------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS snap_decision_record (
            id                      UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               VARCHAR(100) NOT NULL,
            new_fragment_id         UUID        NOT NULL,
            candidate_fragment_id   UUID        NOT NULL,
            evaluated_at            TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            failure_mode_profile    VARCHAR(50) NOT NULL,
            component_scores        JSONB       NOT NULL,
            weights_used            JSONB       NOT NULL,
            raw_composite           FLOAT       NOT NULL,
            temporal_modifier       FLOAT       NOT NULL,
            final_score             FLOAT       NOT NULL,
            threshold_applied       FLOAT       NOT NULL,
            decision                VARCHAR(20) NOT NULL,
            multiple_comparisons_k  INTEGER     NOT NULL DEFAULT 1,
            PRIMARY KEY (id)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sdr_tenant_time "
        "ON snap_decision_record (tenant_id, evaluated_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sdr_new_frag "
        "ON snap_decision_record (new_fragment_id)"
    )

    # -- cluster_snapshot (Audit §7.3) ----------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS cluster_snapshot (
            id                      UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               VARCHAR(100) NOT NULL,
            evaluated_at            TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            member_fragment_ids     JSONB       NOT NULL,
            edges                   JSONB       NOT NULL,
            cluster_score           FLOAT       NOT NULL,
            correlation_discount    FLOAT       NOT NULL,
            adjusted_score          FLOAT       NOT NULL,
            threshold               FLOAT       NOT NULL,
            decision                VARCHAR(20) NOT NULL,
            PRIMARY KEY (id)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cs_tenant_time "
        "ON cluster_snapshot (tenant_id, evaluated_at)"
    )

    # -- cold_fragment (Phase 5: pgvector ANN cold storage) --------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS cold_fragment (
            id                      UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               VARCHAR(100) NOT NULL,
            original_fragment_id    UUID        NOT NULL,
            source_type             VARCHAR(50) NOT NULL,
            raw_content_summary     TEXT,
            extracted_entities      JSONB       DEFAULT '[]'::jsonb,
            failure_mode_tags       JSONB       DEFAULT '[]'::jsonb,
            enriched_embedding      vector(1536),
            event_timestamp         TIMESTAMP WITH TIME ZONE,
            archived_at             TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            original_created_at     TIMESTAMP WITH TIME ZONE,
            original_decay_score    FLOAT       NOT NULL DEFAULT 0.0,
            snap_status_at_archive  VARCHAR(20) NOT NULL DEFAULT 'EXPIRED',
            PRIMARY KEY (id)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cold_frag_tenant "
        "ON cold_fragment (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cold_frag_original "
        "ON cold_fragment (original_fragment_id)"
    )
    # IVFFlat ANN index for cosine similarity search
    # lists=100 is suitable for up to ~1M rows; adjust for larger datasets
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_cold_frag_embedding_ann
        ON cold_fragment
        USING ivfflat (enriched_embedding vector_cosine_ops)
        WITH (lists = 100)
    """)

    # -- New columns on abeyance_fragment --------------------------------------

    # embedding_mask — which sub-vectors are valid (INV-11)
    op.execute("""
        ALTER TABLE abeyance_fragment
        ADD COLUMN IF NOT EXISTS embedding_mask JSONB
            DEFAULT '[true, false, true, false]'::jsonb
    """)

    # dedup_key — deduplication hash (Phase 7, §7.3)
    op.execute("""
        ALTER TABLE abeyance_fragment
        ADD COLUMN IF NOT EXISTS dedup_key VARCHAR(500)
    """)

    # max_lifetime_days — hard lifetime bound (INV-6)
    op.execute("""
        ALTER TABLE abeyance_fragment
        ADD COLUMN IF NOT EXISTS max_lifetime_days INTEGER DEFAULT 730
    """)

    # Dedup unique constraint (tenant-scoped)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_fragment_dedup
        ON abeyance_fragment (tenant_id, dedup_key)
        WHERE dedup_key IS NOT NULL
    """)

    # Change default snap_status from ABEYANCE to INGESTED
    op.execute("""
        ALTER TABLE abeyance_fragment
        ALTER COLUMN snap_status SET DEFAULT 'INGESTED'
    """)

    # Additional tenant-scoped index on created_at
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_abeyance_fragment_tenant_created "
        "ON abeyance_fragment (tenant_id, created_at)"
    )

    # -- Remediate accumulation_edge uniqueness (Audit §9.2) -------------------
    # Drop old non-tenant-scoped unique index if it exists
    op.execute("DROP INDEX IF EXISTS ix_accum_edge_pair")

    # Create tenant-scoped uniqueness
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_accum_edge_pair "
        "ON accumulation_edge (tenant_id, fragment_a_id, fragment_b_id)"
    )

    # Add tenant-scoped fragment indexes on accumulation_edge
    op.execute("DROP INDEX IF EXISTS ix_accum_edge_fragment_a")
    op.execute("DROP INDEX IF EXISTS ix_accum_edge_fragment_b")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_accum_edge_frag_a "
        "ON accumulation_edge (tenant_id, fragment_a_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_accum_edge_frag_b "
        "ON accumulation_edge (tenant_id, fragment_b_id)"
    )

    # -- Update decay partial index to cover ACTIVE + NEAR_MISS ----------------
    op.execute("DROP INDEX IF EXISTS ix_abeyance_fragment_decay")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_abeyance_fragment_tenant_decay "
        "ON abeyance_fragment (tenant_id, current_decay_score) "
        "WHERE snap_status IN ('ACTIVE', 'NEAR_MISS')"
    )


def downgrade() -> None:
    """Remove provenance tables and new columns."""
    # Restore old indexes
    op.execute("DROP INDEX IF EXISTS ix_abeyance_fragment_tenant_decay")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_abeyance_fragment_decay "
        "ON abeyance_fragment (current_decay_score) "
        "WHERE snap_status = 'ABEYANCE'"
    )
    op.execute("DROP INDEX IF EXISTS ix_accum_edge_frag_a")
    op.execute("DROP INDEX IF EXISTS ix_accum_edge_frag_b")
    op.execute("DROP INDEX IF EXISTS ix_accum_edge_pair")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_accum_edge_pair "
        "ON accumulation_edge (fragment_a_id, fragment_b_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_accum_edge_fragment_a "
        "ON accumulation_edge (fragment_a_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_accum_edge_fragment_b "
        "ON accumulation_edge (fragment_b_id)"
    )

    op.execute("DROP INDEX IF EXISTS ix_abeyance_fragment_tenant_created")
    op.execute("""
        ALTER TABLE abeyance_fragment
        ALTER COLUMN snap_status SET DEFAULT 'ABEYANCE'
    """)
    op.execute("DROP INDEX IF EXISTS uq_fragment_dedup")
    op.execute("ALTER TABLE abeyance_fragment DROP COLUMN IF EXISTS max_lifetime_days")
    op.execute("ALTER TABLE abeyance_fragment DROP COLUMN IF EXISTS dedup_key")
    op.execute("ALTER TABLE abeyance_fragment DROP COLUMN IF EXISTS embedding_mask")

    op.execute("DROP TABLE IF EXISTS cold_fragment")
    op.execute("DROP TABLE IF EXISTS cluster_snapshot")
    op.execute("DROP TABLE IF EXISTS snap_decision_record")
    op.execute("DROP TABLE IF EXISTS fragment_history")
