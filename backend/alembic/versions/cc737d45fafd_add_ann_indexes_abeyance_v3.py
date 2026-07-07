"""Add ANN (IVFFlat cosine) indexes for abeyance v3 embedding columns

Revision ID: cc737d45fafd
Revises: 022_add_must_change_password
Create Date: 2026-07-07 00:00:00.000000

Changes:
  abeyance_fragment.emb_semantic     — IVFFlat cosine index (vector_cosine_ops, lists=100)
  abeyance_fragment.emb_topological  — IVFFlat cosine index (vector_cosine_ops, lists=100)

  Prevents sequential scans during ANN retrieval over the v3 embedding columns.
  PostgreSQL + pgvector only; a no-op on non-postgres backends (e.g. SQLite).
  Adds INDEXES only — no new tables.
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "cc737d45fafd"
down_revision = "022_add_must_change_password"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_abeyance_frag_emb_semantic_ivf "
        "ON abeyance_fragment USING ivfflat (emb_semantic vector_cosine_ops) "
        "WITH (lists = 100)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_abeyance_frag_emb_topological_ivf "
        "ON abeyance_fragment USING ivfflat (emb_topological vector_cosine_ops) "
        "WITH (lists = 100)"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_abeyance_frag_emb_semantic_ivf")
    op.execute("DROP INDEX IF EXISTS ix_abeyance_frag_emb_topological_ivf")
