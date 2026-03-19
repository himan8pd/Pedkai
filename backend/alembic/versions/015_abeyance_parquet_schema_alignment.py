"""Abeyance Memory parquet schema alignment

Revision ID: 015_abeyance_parquet_schema_alignment
Revises: 014_add_missing_core_tables
Create Date: 2026-03-18 18:57:00.000000

Fixes column mismatches between the 7 abeyance_memory/*.parquet files
produced by the Six Telecom synthetic data generator and the existing
Abeyance Memory v3 DB schema.

Changes:
  abeyance_fragment:
    + entity_count INTEGER NOT NULL DEFAULT 0
    + snap_partner_id UUID (nullable)

  entity_sequence_log:
    + is_rare BOOLEAN NOT NULL DEFAULT FALSE
    + transition_count_hint INTEGER NOT NULL DEFAULT 0

  causal_evidence_pair:
    + direction_category VARCHAR(50) (nullable)

  bridge_discovery:
    + entity_domains_spanned JSONB (nullable)
    + sub_component_size INTEGER (nullable)

  disconfirmation_events:
    * initiated_by SET DEFAULT 'SYNTHETIC_SEED'   (relaxes NOT NULL for seeded loads)
    * fragment_count SET DEFAULT 0                (ensures parquet rows without this field succeed)

All operations use ADD COLUMN IF NOT EXISTS / ALTER COLUMN ... SET DEFAULT
and are fully backward-compatible with existing data.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '015_abeyance_schema_fix'
down_revision: Union[str, Sequence[str], None] = '014_add_missing_core_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Widen alembic_version.version_num in case this instance has VARCHAR(32).
    # Standard Alembic default is VARCHAR(32); our IDs exceed that.
    # This is idempotent — widening a varchar column never loses data.
    op.execute("""
        ALTER TABLE alembic_version
        ALTER COLUMN version_num TYPE VARCHAR(64)
    """)

    # ------------------------------------------------------------------
    # abeyance_fragment — two new columns for parquet ingestion
    # ------------------------------------------------------------------
    # entity_count: parquet has this as an int32 field, the DB currently
    # derives entity count from the extracted_entities JSONB array length.
    # Adding a denormalised integer for direct parquet loading.
    op.execute("""
        ALTER TABLE abeyance_fragment
        ADD COLUMN IF NOT EXISTS entity_count INTEGER NOT NULL DEFAULT 0
    """)

    # snap_partner_id: present in abeyance_fragments.parquet but not in DB.
    # Nullable UUID — references the "snap partner" fragment when a snap
    # event pairs two fragments together.
    op.execute("""
        ALTER TABLE abeyance_fragment
        ADD COLUMN IF NOT EXISTS snap_partner_id UUID
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_abeyance_fragment_snap_partner
        ON abeyance_fragment (tenant_id, snap_partner_id)
        WHERE snap_partner_id IS NOT NULL
    """)

    # ------------------------------------------------------------------
    # entity_sequence_log — two new columns from temporal_sequences.parquet
    # ------------------------------------------------------------------
    # is_rare: flags whether this state transition is statistically rare
    # (used by the expectation violation engine).
    op.execute("""
        ALTER TABLE entity_sequence_log
        ADD COLUMN IF NOT EXISTS is_rare BOOLEAN NOT NULL DEFAULT FALSE
    """)

    # transition_count_hint: generator-supplied hint for how many times
    # this transition has been observed during the simulation window.
    op.execute("""
        ALTER TABLE entity_sequence_log
        ADD COLUMN IF NOT EXISTS transition_count_hint INTEGER NOT NULL DEFAULT 0
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_esl_tenant_rare
        ON entity_sequence_log (tenant_id, is_rare)
        WHERE is_rare = TRUE
    """)

    # ------------------------------------------------------------------
    # causal_evidence_pair — direction_category from causal_pairs.parquet
    # ------------------------------------------------------------------
    # The parquet has `direction_category` (e.g. 'STRONG_A_TO_B',
    # 'BIDIRECTIONAL') alongside the boolean `a_precedes_b`.
    # The existing `direction` column stores the translated boolean as
    # 'A_TO_B'/'B_TO_A'; direction_category stores the richer label.
    op.execute("""
        ALTER TABLE causal_evidence_pair
        ADD COLUMN IF NOT EXISTS direction_category VARCHAR(50)
    """)

    # ------------------------------------------------------------------
    # bridge_discovery — two new columns from bridge_candidates.parquet
    # ------------------------------------------------------------------
    # entity_domains_spanned: JSON array of domain strings that the bridge
    # fragment spans (e.g. ["mobile_ran", "transport"]).
    op.execute("""
        ALTER TABLE bridge_discovery
        ADD COLUMN IF NOT EXISTS entity_domains_spanned JSONB
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_bridge_domains_gin
        ON bridge_discovery
        USING gin (entity_domains_spanned jsonb_path_ops)
        WHERE entity_domains_spanned IS NOT NULL
    """)

    # sub_component_size: number of fragments in the subgraph component
    # that this bridge node connects.
    op.execute("""
        ALTER TABLE bridge_discovery
        ADD COLUMN IF NOT EXISTS sub_component_size INTEGER
    """)

    # ------------------------------------------------------------------
    # disconfirmation_events — relax NOT NULL for seeded parquet loads
    # ------------------------------------------------------------------
    # The parquet file is denormalised (one row per fragment, not per
    # batch event). The `initiated_by` and `fragment_count` fields are
    # absent. Adding server defaults avoids NOT NULL failures during
    # generic passthrough ingestion while preserving the constraint for
    # application-generated rows.
    op.execute("""
        ALTER TABLE disconfirmation_events
        ALTER COLUMN initiated_by SET DEFAULT 'SYNTHETIC_SEED'
    """)
    op.execute("""
        ALTER TABLE disconfirmation_events
        ALTER COLUMN fragment_count SET DEFAULT 0
    """)


def downgrade() -> None:
    # Restore disconfirmation_events columns to their original state
    op.execute("""
        ALTER TABLE disconfirmation_events
        ALTER COLUMN fragment_count DROP DEFAULT
    """)
    op.execute("""
        ALTER TABLE disconfirmation_events
        ALTER COLUMN initiated_by DROP DEFAULT
    """)

    # Drop bridge_discovery additions
    op.execute("DROP INDEX IF EXISTS ix_bridge_domains_gin")
    op.execute("ALTER TABLE bridge_discovery DROP COLUMN IF EXISTS sub_component_size")
    op.execute("ALTER TABLE bridge_discovery DROP COLUMN IF EXISTS entity_domains_spanned")

    # Drop causal_evidence_pair addition
    op.execute("ALTER TABLE causal_evidence_pair DROP COLUMN IF EXISTS direction_category")

    # Drop entity_sequence_log additions
    op.execute("DROP INDEX IF EXISTS ix_esl_tenant_rare")
    op.execute("ALTER TABLE entity_sequence_log DROP COLUMN IF EXISTS transition_count_hint")
    op.execute("ALTER TABLE entity_sequence_log DROP COLUMN IF EXISTS is_rare")

    # Drop abeyance_fragment additions
    op.execute("DROP INDEX IF EXISTS ix_abeyance_fragment_snap_partner")
    op.execute("ALTER TABLE abeyance_fragment DROP COLUMN IF EXISTS snap_partner_id")
    op.execute("ALTER TABLE abeyance_fragment DROP COLUMN IF EXISTS entity_count")
