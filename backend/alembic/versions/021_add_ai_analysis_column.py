"""Add ai_analysis JSONB column to reconciliation_results

Revision ID: 021_add_ai_analysis_column
Revises: 020_tenant_scoped_username
Create Date: 2026-03-24 12:00:00.000000

Changes:
  reconciliation_results.ai_analysis  — new JSONB column (nullable)
  Stores pre-computed LLM analysis from the batch AI service so the
  divergence UI can display AI insights instantly.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "021_add_ai_analysis_column"
down_revision = "020_tenant_scoped_username"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guard: only add if column doesn't already exist (idempotent for
    # environments where init_db.py already created it from the ORM).
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'reconciliation_results' "
            "AND column_name = 'ai_analysis'"
        )
    )
    if result.fetchone() is None:
        op.add_column(
            "reconciliation_results",
            sa.Column("ai_analysis", JSONB, nullable=True),
        )


def downgrade() -> None:
    op.drop_column("reconciliation_results", "ai_analysis")
