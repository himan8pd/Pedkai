"""Enforce tenant isolation on BSS, Causal, and all remaining tables missing tenant_id

Revision ID: 017_tenant_isolation_bss_causal
Revises: 016_tenant_admin
Create Date: 2026-03-19 13:00:00.000000

Changes (11 tables):
  bss_service_plans         + tenant_id NOT NULL + index
  bss_billing_accounts      + tenant_id NOT NULL + index
  causal_evidence_pair      + tenant_id NOT NULL + ix_causal_ev_tenant
  disconfirmation_fragments + tenant_id NOT NULL + index
  bridge_discovery_provenance + tenant_id NOT NULL + index
  hypothesis_evidence       + tenant_id NOT NULL + index
  counterfactual_pair_delta + tenant_id NOT NULL + index
  meta_memory_productivity  + tenant_id NOT NULL + index
  proactive_care_records    + tenant_id NOT NULL + index
  decision_feedback         + tenant_id NOT NULL + index
  investment_plans          + tenant_id NOT NULL + index

Note: server_default='unknown' is a safety valve for live migrations. In practice the
database will be wiped and re-seeded, so no rows with 'unknown' will survive to production.
"""

from alembic import op
import sqlalchemy as sa

revision = "017_tenant_isolation_bss_causal"
down_revision = "016_tenant_admin"
branch_labels = None
depends_on = None


def _add_tenant_id(table: str, index_name: str) -> None:
    op.add_column(
        table,
        sa.Column("tenant_id", sa.String(100), nullable=False, server_default="unknown"),
    )
    op.create_index(index_name, table, ["tenant_id"])
    # Remove the server_default now that existing rows have been backfilled.
    # Without this, any future raw INSERT that omits tenant_id silently gets
    # 'unknown' instead of a NOT NULL violation — breaking the isolation contract.
    op.alter_column(table, "tenant_id", existing_type=sa.String(100), server_default=None)


def _drop_tenant_id(table: str, index_name: str) -> None:
    op.drop_index(index_name, table_name=table)
    op.drop_column(table, "tenant_id")


def upgrade() -> None:
    _add_tenant_id("bss_service_plans",          "ix_bss_service_plans_tenant_id")
    # Swap the global unique(name) for a tenant-scoped composite.
    # Without this, ON CONFLICT (name) matches across tenants — silent data corruption.
    op.execute("ALTER TABLE bss_service_plans DROP CONSTRAINT IF EXISTS bss_service_plans_name_key")
    op.create_unique_constraint(
        "uq_bss_service_plans_tenant_name", "bss_service_plans", ["tenant_id", "name"]
    )
    _add_tenant_id("bss_billing_accounts",        "ix_bss_billing_accounts_tenant_id")
    _add_tenant_id("causal_evidence_pair",        "ix_causal_ev_tenant")
    _add_tenant_id("disconfirmation_fragments",   "ix_disconf_frag_tenant")
    _add_tenant_id("bridge_discovery_provenance", "ix_bridge_prov_tenant")
    _add_tenant_id("hypothesis_evidence",         "ix_hyp_ev_tenant")
    _add_tenant_id("counterfactual_pair_delta",   "ix_cf_delta_tenant")
    _add_tenant_id("meta_memory_productivity",    "ix_mmp_tenant")
    _add_tenant_id("proactive_care_records",      "ix_proactive_care_tenant_id")
    _add_tenant_id("decision_feedback",           "ix_decision_feedback_tenant_id")
    _add_tenant_id("investment_plans",            "ix_investment_plans_tenant_id")


def downgrade() -> None:
    _drop_tenant_id("investment_plans",            "ix_investment_plans_tenant_id")
    _drop_tenant_id("decision_feedback",           "ix_decision_feedback_tenant_id")
    _drop_tenant_id("proactive_care_records",      "ix_proactive_care_tenant_id")
    _drop_tenant_id("meta_memory_productivity",    "ix_mmp_tenant")
    _drop_tenant_id("counterfactual_pair_delta",   "ix_cf_delta_tenant")
    _drop_tenant_id("hypothesis_evidence",         "ix_hyp_ev_tenant")
    _drop_tenant_id("bridge_discovery_provenance", "ix_bridge_prov_tenant")
    _drop_tenant_id("disconfirmation_fragments",   "ix_disconf_frag_tenant")
    _drop_tenant_id("causal_evidence_pair",        "ix_causal_ev_tenant")
    _drop_tenant_id("bss_billing_accounts",        "ix_bss_billing_accounts_tenant_id")
    # Reverse the constraint swap before dropping tenant_id
    op.drop_constraint("uq_bss_service_plans_tenant_name", "bss_service_plans", type_="unique")
    op.create_unique_constraint("bss_service_plans_name_key", "bss_service_plans", ["name"])
    _drop_tenant_id("bss_service_plans",           "ix_bss_service_plans_tenant_id")
