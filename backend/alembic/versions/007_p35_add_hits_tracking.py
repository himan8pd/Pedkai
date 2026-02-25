"""P3.5: Add hits and evidence count to decision_traces

Revision ID: 007_add_hits_tracking
Revises: 006_add_feedback_comment
Create Date: 2026-02-24 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '007_add_hits_tracking'
down_revision: Union[str, Sequence[str], None] = '006_add_feedback_comment'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add memory_hits and causal_evidence_count to decision_traces."""
    op.add_column('decision_traces', sa.Column('memory_hits', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('decision_traces', sa.Column('causal_evidence_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Remove memory_hits and causal_evidence_count from decision_traces."""
    op.drop_column('decision_traces', 'causal_evidence_count')
    op.drop_column('decision_traces', 'memory_hits')
