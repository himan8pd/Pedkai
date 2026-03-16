"""Add heuristic_used flag to counterfactual_simulation_result

Revision ID: 013_counterflag
Revises: 012_abeyance_v3_tables
Create Date: 2026-03-16 18:00:00.000000

Adds:
- heuristic_used boolean column to counterfactual_simulation_result
  Defaults to True since all existing results used the subtraction heuristic.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '013_counterflag'
down_revision: Union[str, Sequence[str], None] = '012_abeyance_v3_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'counterfactual_simulation_result',
        sa.Column('heuristic_used', sa.Boolean(), nullable=False, server_default='true'),
    )


def downgrade() -> None:
    op.drop_column('counterfactual_simulation_result', 'heuristic_used')
