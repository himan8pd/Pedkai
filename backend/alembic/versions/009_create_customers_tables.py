"""Create customers and proactive_care_records tables

Revision ID: 009_create_customers_tables
Revises: 008_abeyance_decay
Create Date: 2026-03-14 00:00:00.000000

Creates the CX Intelligence tables required by CXIntelligenceService and
ProactiveCommsService.  Uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS so the
migration is safe to run against DBs that were previously bootstrapped via
Base.metadata.create_all.

Tables:
- customers              — customer profiles with GDPR consent flag
- proactive_care_records — log of proactive notifications (always draft/simulation)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '009_create_customers_tables'
down_revision: Union[str, Sequence[str], None] = '008_abeyance_decay'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create customers and proactive_care_records tables (idempotent)."""

    # -- customers table ---------------------------------------------------
    # CREATE TABLE IF NOT EXISTS so we don't fail on DBs that already have
    # the table from a prior Base.metadata.create_all call.
    op.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id                      UUID        NOT NULL DEFAULT gen_random_uuid(),
            external_id             VARCHAR(100) NOT NULL,
            name                    VARCHAR(255),
            churn_risk_score        FLOAT       DEFAULT 0.0,
            associated_site_id      VARCHAR(255),
            consent_proactive_comms BOOLEAN     NOT NULL DEFAULT FALSE,
            tenant_id               VARCHAR(100) NOT NULL,
            created_at              TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE (external_id)
        )
    """)

    # If the table already existed without the consent column, add it now.
    # ADD COLUMN IF NOT EXISTS is idempotent on Postgres 9.6+.
    op.execute("""
        ALTER TABLE customers
            ADD COLUMN IF NOT EXISTS
            consent_proactive_comms BOOLEAN NOT NULL DEFAULT FALSE
    """)

    # Indexes (IF NOT EXISTS so reruns are harmless)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_customers_external_id "
        "ON customers (external_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_customers_tenant_id "
        "ON customers (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_customers_associated_site_id "
        "ON customers (associated_site_id)"
    )

    # -- proactive_care_records table --------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS proactive_care_records (
            id               UUID        NOT NULL DEFAULT gen_random_uuid(),
            customer_id      UUID        NOT NULL REFERENCES customers(id),
            anomaly_id       UUID,
            channel          VARCHAR(50) DEFAULT 'simulation',
            status           VARCHAR(50) DEFAULT 'triggered',
            message_content  TEXT,
            created_at       TIMESTAMP,
            PRIMARY KEY (id)
        )
    """)


def downgrade() -> None:
    """Drop customers and proactive_care_records tables."""
    op.execute("DROP TABLE IF EXISTS proactive_care_records")
    op.execute("DROP TABLE IF EXISTS customers")
