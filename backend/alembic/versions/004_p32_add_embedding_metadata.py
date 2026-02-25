"""P3.2: Add embedding provider to decision_traces

Revision ID: 004_add_embedding_metadata
Revises: 003_add_incidents
Create Date: 2026-02-24 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '004_add_embedding_metadata'
down_revision: Union[str, Sequence[str], None] = '003_add_incidents'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add embedding provider metadata to decision_traces."""
    op.add_column('decision_traces', sa.Column('embedding_provider', sa.String(length=50), nullable=True))
    op.add_column('decision_traces', sa.Column('embedding_model', sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Remove embedding provider metadata from decision_traces."""
    op.drop_column('decision_traces', 'embedding_model')
    op.drop_column('decision_traces', 'embedding_provider')
