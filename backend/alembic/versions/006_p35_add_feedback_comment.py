"""P3.5: Add comment to decision_feedback

Revision ID: 006_add_feedback_comment
Revises: 005_add_tmf_fields
Create Date: 2026-02-24 18:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '006_add_feedback_comment'
down_revision: Union[str, Sequence[str], None] = '005_add_tmf_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add comment column to decision_feedback."""
    op.add_column('decision_feedback', sa.Column('comment', sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove comment column from decision_feedback."""
    op.drop_column('decision_feedback', 'comment')
