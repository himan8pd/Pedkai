"""P3.2: Add missing TMF fields to decision_traces

Revision ID: 005_add_tmf_fields
Revises: 004_add_embedding_metadata
Create Date: 2026-02-24 18:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005_add_tmf_fields'
down_revision: Union[str, Sequence[str], None] = '004_add_embedding_metadata'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add missing TMF642 compatibility fields to decision_traces."""
    op.add_column('decision_traces', sa.Column('entity_id', sa.String(length=255), nullable=True))
    op.add_column('decision_traces', sa.Column('entity_type', sa.String(length=50), nullable=True))
    op.add_column('decision_traces', sa.Column('title', sa.String(length=500), nullable=True))
    op.add_column('decision_traces', sa.Column('severity', sa.String(length=50), nullable=True, server_default='minor'))
    op.add_column('decision_traces', sa.Column('status', sa.String(length=50), nullable=True, server_default='raised'))
    
    # Add index for entity_id
    op.create_index('ix_decision_traces_entity_id', 'decision_traces', ['entity_id'], unique=False)


def downgrade() -> None:
    """Remove TMF642 compatibility fields from decision_traces."""
    op.drop_index('ix_decision_traces_entity_id', table_name='decision_traces')
    op.drop_column('decision_traces', 'status')
    op.drop_column('decision_traces', 'severity')
    op.drop_column('decision_traces', 'title')
    op.drop_column('decision_traces', 'entity_type')
    op.drop_column('decision_traces', 'entity_id')
