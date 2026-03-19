"""Add per-tenant role + granted_by to user_tenant_access

Revision ID: 016_tenant_admin
Revises: 015_abeyance_parquet_schema_alignment
Create Date: 2026-03-19 12:00:00.000000

Changes:
  user_tenant_access:
    + role       VARCHAR(50) NULL  — per-tenant role override (NULL = use UserORM.role)
    + granted_by VARCHAR(36) NULL  — user_id of who granted the access (audit trail)
"""

from alembic import op
import sqlalchemy as sa

revision = "016_tenant_admin"
down_revision = "015_abeyance_parquet_schema_alignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_tenant_access",
        sa.Column("role", sa.String(50), nullable=True),
    )
    op.add_column(
        "user_tenant_access",
        sa.Column("granted_by", sa.String(36), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_tenant_access", "granted_by")
    op.drop_column("user_tenant_access", "role")
