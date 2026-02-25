"""P1.1: Create network_entities table

Revision ID: 001_add_network_entities
Revises: 96488105820a
Create Date: 2026-02-23 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_add_network_entities'
down_revision: Union[str, Sequence[str], None] = '96488105820a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create network_entities table with all required columns."""
    op.create_table(
        'network_entities',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('tenant_id', sa.String(length=50), nullable=False),
        sa.Column('entity_type', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('external_id', sa.String(length=255), nullable=True),
        sa.Column('geo_lat', sa.Float(), nullable=True),
        sa.Column('geo_lon', sa.Float(), nullable=True),
        sa.Column('revenue_weight', sa.Float(), nullable=True),
        sa.Column('sla_tier', sa.String(length=50), nullable=True),
        sa.Column('embedding_provider', sa.String(length=50), nullable=True),
        sa.Column('embedding_model', sa.String(length=100), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes
    op.create_index('ix_network_entities_tenant_id', 'network_entities', ['tenant_id'], unique=False)
    op.create_index('ix_network_entities_entity_type', 'network_entities', ['entity_type'], unique=False)
    op.create_index('ix_network_entities_external_id', 'network_entities', ['external_id', 'tenant_id'], unique=False)
    op.create_index('ix_network_entities_tenant_type', 'network_entities', ['tenant_id', 'entity_type'], unique=False)


def downgrade() -> None:
    """Drop network_entities table."""
    op.drop_index('ix_network_entities_tenant_type', table_name='network_entities')
    op.drop_index('ix_network_entities_external_id', table_name='network_entities')
    op.drop_index('ix_network_entities_entity_type', table_name='network_entities')
    op.drop_index('ix_network_entities_tenant_id', table_name='network_entities')
    op.drop_table('network_entities')
