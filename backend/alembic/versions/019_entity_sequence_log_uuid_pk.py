"""019 — Change entity_sequence_log PK from BIGSERIAL to UUID.

The generator's temporal_sequences.parquet uses UUIDv7 `seq_id` as the
primary key, but the original DDL (migration 012) used BIGSERIAL.
This migration changes the column type so the loader can use the parquet's
deterministic UUID as the PK (enables ON CONFLICT idempotency).

This migration is safe on a freshly rebuilt database (no existing data).
On an existing database with BIGSERIAL data, it would fail — but the
recovery plan calls for a full rebuild before applying these migrations.

Revision ID: 019_entity_sequence_log_uuid_pk
Revises: 018_harmonize_tenant_id_widths
Create Date: 2026-03-20
"""
from alembic import op
import sqlalchemy as sa

revision = "019_entity_sequence_log_uuid_pk"
down_revision = "018_harmonize_tenant_id_widths"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the existing BIGSERIAL default before changing type
    op.execute("""
        ALTER TABLE entity_sequence_log
        ALTER COLUMN id DROP DEFAULT
    """)
    op.execute("""
        ALTER TABLE entity_sequence_log
        ALTER COLUMN id TYPE UUID USING gen_random_uuid()
    """)
    # Drop the associated sequence (BIGSERIAL creates one implicitly)
    op.execute("""
        DROP SEQUENCE IF EXISTS entity_sequence_log_id_seq
    """)


def downgrade() -> None:
    # Revert to BIGSERIAL — data loss on the UUID values is expected
    op.execute("""
        CREATE SEQUENCE IF NOT EXISTS entity_sequence_log_id_seq
    """)
    op.execute("""
        ALTER TABLE entity_sequence_log
        ALTER COLUMN id TYPE BIGINT USING 0
    """)
    op.execute("""
        ALTER TABLE entity_sequence_log
        ALTER COLUMN id SET DEFAULT nextval('entity_sequence_log_id_seq')
    """)
