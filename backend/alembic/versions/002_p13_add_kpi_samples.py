"""P1.3: Create kpi_samples table

Revision ID: 002_add_kpi_samples
Revises: 001_add_network_entities
Create Date: 2026-02-23 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002_add_kpi_samples'
down_revision: Union[str, Sequence[str], None] = '001_add_network_entities'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create kpi_samples table with foreign key to network_entities."""
    op.create_table(
        'kpi_samples',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('tenant_id', sa.String(length=50), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('metric_name', sa.String(length=100), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['entity_id'], ['network_entities.id'], ondelete='CASCADE')
    )
    
    # Create indexes for time-series queries
    op.create_index('ix_kpi_tenant_id', 'kpi_samples', ['tenant_id'], unique=False)
    op.create_index('ix_kpi_entity_id', 'kpi_samples', ['entity_id'], unique=False)
    op.create_index('ix_kpi_metric_name', 'kpi_samples', ['metric_name'], unique=False)
    
    # Composite indexes for common query patterns
    op.create_index('ix_kpi_entity_metric_time', 'kpi_samples', 
                   ['entity_id', 'metric_name', 'timestamp'], unique=False)
    op.create_index('ix_kpi_tenant_entity_metric', 'kpi_samples', 
                   ['tenant_id', 'entity_id', 'metric_name'], unique=False)


def downgrade() -> None:
    """Drop kpi_samples table."""
    op.drop_index('ix_kpi_tenant_entity_metric', table_name='kpi_samples')
    op.drop_index('ix_kpi_entity_metric_time', table_name='kpi_samples')
    op.drop_index('ix_kpi_metric_name', table_name='kpi_samples')
    op.drop_index('ix_kpi_entity_id', table_name='kpi_samples')
    op.drop_index('ix_kpi_tenant_id', table_name='kpi_samples')
    op.drop_table('kpi_samples')
