"""P2.1: Add incidents table

Revision ID: 003_add_incidents
Revises: 002_add_kpi_samples
Create Date: 2026-02-24 16:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '003_add_incidents'
down_revision: Union[str, Sequence[str], None] = '002_add_kpi_samples'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create incidents table."""
    op.create_table(
        'incidents',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('tenant_id', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('entity_id', sa.String(length=36), nullable=True),
        sa.Column('entity_external_id', sa.String(length=255), nullable=True),
        sa.Column('decision_trace_id', sa.String(length=36), nullable=True),
        sa.Column('reasoning_chain', sa.JSON(), nullable=True),
        sa.Column('resolution_summary', sa.Text(), nullable=True),
        sa.Column('kpi_snapshot', sa.JSON(), nullable=True),
        sa.Column('llm_model_version', sa.String(length=100), nullable=True),
        sa.Column('llm_prompt_hash', sa.String(length=32), nullable=True),
        sa.Column('sitrep_approved_by', sa.String(length=255), nullable=True),
        sa.Column('sitrep_approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('action_approved_by', sa.String(length=255), nullable=True),
        sa.Column('action_approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closed_by', sa.String(length=255), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_incidents_entity_id', 'incidents', ['entity_id'], unique=False)
    op.create_index('ix_incidents_severity', 'incidents', ['severity'], unique=False)
    op.create_index('ix_incidents_status', 'incidents', ['status'], unique=False)
    op.create_index('ix_incidents_tenant_id', 'incidents', ['tenant_id'], unique=False)


def downgrade() -> None:
    """Drop incidents table."""
    op.drop_index('ix_incidents_tenant_id', table_name='incidents')
    op.drop_index('ix_incidents_status', table_name='incidents')
    op.drop_index('ix_incidents_severity', table_name='incidents')
    op.drop_index('ix_incidents_entity_id', table_name='incidents')
    op.drop_table('incidents')
