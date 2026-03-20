"""018 — Harmonize tenant_id column widths.

Standardise all tenant_id columns to VARCHAR(100) to match TenantORM.id.
Previously, columns ranged from VARCHAR(36) to VARCHAR(255) depending on
when the ORM model was written.

Revision ID: 018_harmonize_tenant_id_widths
Revises: 017_tenant_isolation_bss_causal
Create Date: 2026-03-20
"""
from alembic import op
import sqlalchemy as sa

revision = "018_harmonize_tenant_id_widths"
down_revision = "017_tenant_isolation_bss_causal"
branch_labels = None
depends_on = None

# Tables whose tenant_id was VARCHAR(36)
_FROM_36 = [
    "policies",
    "policy_evaluations",
    "policy_versions",
    "action_executions",
]

# Tables whose tenant_id was VARCHAR(50)
_FROM_50 = [
    "incidents",
    "incident_audit_entries",
    "network_entities",
    "topology_relationships",
    "kpi_samples",
]

# Tables whose tenant_id was VARCHAR(255) — note kpi_metrics.tenant_id
# is part of the composite PK, handled separately.
_FROM_255 = [
    "decision_traces",
]


def upgrade() -> None:
    for table in _FROM_36 + _FROM_50 + _FROM_255:
        op.alter_column(
            table,
            "tenant_id",
            type_=sa.String(100),
            existing_type=sa.String(),  # Any existing width
            existing_nullable=False,
        )

    # kpi_metrics lives on the metrics DB and is not managed by Alembic.
    # Its tenant_id width change (VARCHAR(255) → VARCHAR(100)) must be
    # applied manually on the metrics database:
    #
    #   ALTER TABLE kpi_metrics ALTER COLUMN tenant_id TYPE VARCHAR(100);


def downgrade() -> None:
    for table in _FROM_36:
        op.alter_column(table, "tenant_id", type_=sa.String(36), existing_nullable=False)
    for table in _FROM_50:
        op.alter_column(table, "tenant_id", type_=sa.String(50), existing_nullable=False)
    for table in _FROM_255:
        op.alter_column(table, "tenant_id", type_=sa.String(255), existing_nullable=False)
