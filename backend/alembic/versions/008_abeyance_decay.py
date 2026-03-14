"""Abeyance Memory: Add decay scoring columns to decision_traces

Revision ID: 008_abeyance_decay
Revises: 007_add_hits_tracking
Create Date: 2026-03-10 00:00:00.000000

Adds three columns required by the AbeyanceDecayService:
- decay_score: exponential decay value, starts at 1.0, approaches 0 over time
- corroboration_count: how many times this fragment has been corroborated by other evidence
- status: lifecycle state — ACTIVE (default), STALE (decay_score below threshold)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '008_abeyance_decay'
down_revision: Union[str, Sequence[str], None] = '007_add_hits_tracking'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add decay_score, corroboration_count, and abeyance_status to decision_traces.

    Note: 'status' already exists on decision_traces for incident lifecycle
    (raised/cleared). The abeyance lifecycle field is named 'abeyance_status'
    to avoid a column name clash.
    """
    op.add_column(
        'decision_traces',
        sa.Column('decay_score', sa.Float(), nullable=False, server_default='1.0'),
    )
    op.add_column(
        'decision_traces',
        sa.Column('corroboration_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'decision_traces',
        sa.Column('abeyance_status', sa.String(20), nullable=False, server_default='ACTIVE'),
    )


def downgrade() -> None:
    """Remove decay columns from decision_traces."""
    op.drop_column('decision_traces', 'abeyance_status')
    op.drop_column('decision_traces', 'corroboration_count')
    op.drop_column('decision_traces', 'decay_score')
