"""Tenant-scoped username uniqueness

Revision ID: 020_tenant_scoped_username
Revises: 019_entity_sequence_log_uuid_pk
Create Date: 2026-03-22 18:00:00.000000

Changes:
  users.username  — drop global UNIQUE, add composite UNIQUE(tenant_id, username)

This enables different tenants to have users with the same username (e.g. both
tenant A and tenant B can have an "operator" user). Each user row is a fully
independent identity with its own UUID, password, and home tenant.
"""

from alembic import op
import sqlalchemy as sa

revision = "020_tenant_scoped_username"
down_revision = "019_entity_sequence_log_uuid_pk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Safety check: ensure no duplicate (tenant_id, username) pairs exist
    # before adding the composite unique constraint.
    conn = op.get_bind()
    dupes = conn.execute(
        sa.text(
            "SELECT tenant_id, username, COUNT(*) AS cnt "
            "FROM users GROUP BY tenant_id, username HAVING COUNT(*) > 1"
        )
    ).fetchall()
    if dupes:
        msg = "; ".join(f"{r[0]}:{r[1]} ({r[2]}x)" for r in dupes)
        raise RuntimeError(
            f"Cannot apply migration: duplicate (tenant_id, username) pairs exist: {msg}. "
            "Resolve duplicates before retrying."
        )

    # 1. Drop the global unique constraint on username.
    #    The constraint name varies — query pg_constraint to find it.
    row = conn.execute(
        sa.text(
            "SELECT con.conname "
            "FROM pg_constraint con "
            "JOIN pg_class rel ON rel.oid = con.conrelid "
            "JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = ANY(con.conkey) "
            "WHERE rel.relname = 'users' "
            "  AND att.attname = 'username' "
            "  AND con.contype = 'u' "
            "LIMIT 1"
        )
    ).fetchone()
    if row:
        op.drop_constraint(row[0], "users", type_="unique")
    else:
        # May be a unique index instead of a constraint
        conn.execute(sa.text("DROP INDEX IF EXISTS users_username_key"))
        conn.execute(sa.text("DROP INDEX IF EXISTS uq_users_username"))
        conn.execute(sa.text("DROP INDEX IF EXISTS ix_users_username"))

    # 2. Add composite unique constraint: (tenant_id, username)
    op.create_unique_constraint(
        "uq_users_tenant_username", "users", ["tenant_id", "username"]
    )

    # 3. Ensure a non-unique index remains on username for fast lookups
    #    (the old unique constraint served as an index; replace it)
    op.create_index("ix_users_username", "users", ["username"])


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.drop_constraint("uq_users_tenant_username", "users", type_="unique")
    op.create_unique_constraint("users_username_key", "users", ["username"])
