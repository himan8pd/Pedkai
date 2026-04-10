"""Add must_change_password column to users table

Revision ID: 022_add_must_change_password
Revises: 021_add_ai_analysis_column
Create Date: 2026-03-28 12:00:00.000000

Changes:
  users.must_change_password  — new Boolean column (default True)
  Enforces password change on first login for all users.
  Existing users get must_change_password=False (already authenticated).
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "022_add_must_change_password"
down_revision = "021_add_ai_analysis_column"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add column with server_default="0" so existing users are NOT forced to change.
    # New users created after this migration get must_change_password=True via ORM default.
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default="0",  # Existing users: no forced change
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
