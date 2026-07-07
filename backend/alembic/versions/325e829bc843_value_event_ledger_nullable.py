"""Make value_event.ledger_entry_id nullable

Revision ID: 325e829bc843
Revises: cc737d45fafd
Create Date: 2026-07-07 00:00:00.000000

Allows value events that do not stem from a discovery-ledger entry
(e.g. incident-closure events) to be recorded with a NULL
ledger_entry_id.

WARNING: downgrade() is destructive. Because the pre-migration schema
requires ledger_entry_id to be NOT NULL, any rows created after this
migration with a NULL ledger_entry_id cannot be preserved. The
downgrade therefore intentionally DELETEs all value_event rows whose
ledger_entry_id IS NULL before restoring the NOT NULL constraint.

On non-postgres backends (e.g. SQLite) this migration is a no-op.
"""

from alembic import op
from sqlalchemy.dialects import postgresql

revision = "325e829bc843"
down_revision = "cc737d45fafd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.alter_column(
        "value_event",
        "ledger_entry_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    # Destructive: NULL-linked rows cannot satisfy the restored NOT NULL
    # constraint, so they are intentionally deleted here.
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DELETE FROM value_event WHERE ledger_entry_id IS NULL")
    op.alter_column(
        "value_event",
        "ledger_entry_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
