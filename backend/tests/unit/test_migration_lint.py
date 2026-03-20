"""CI guard: every Alembic migration that creates a table must include tenant_id.

Scans all migration files for CREATE TABLE / op.create_table statements and
verifies that a tenant_id column is present unless the table is in the
SYSTEM_TABLES_ALLOWLIST.
"""

import re
from pathlib import Path

from backend.app.core.database import SYSTEM_TABLES_ALLOWLIST

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"

# Regex patterns for raw SQL CREATE TABLE and Alembic op.create_table
_CREATE_TABLE_SQL = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\")?(\w+)(?:\")?\s*\(",
    re.IGNORECASE,
)
_OP_CREATE_TABLE = re.compile(
    r"op\.create_table\(\s*['\"](\w+)['\"]",
)


def _extract_create_table_blocks(content: str) -> list[tuple[str, str]]:
    """Return (table_name, block_text) for each CREATE TABLE in the file."""
    results = []
    for m in _CREATE_TABLE_SQL.finditer(content):
        table_name = m.group(1)
        start = m.start()
        # Find the matching closing paren — crude but sufficient for lint
        depth = 0
        block_end = start
        for i, ch in enumerate(content[start:], start=start):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    block_end = i
                    break
        results.append((table_name, content[start:block_end + 1]))
    for m in _OP_CREATE_TABLE.finditer(content):
        table_name = m.group(1)
        start = m.start()
        depth = 0
        block_end = start
        for i, ch in enumerate(content[start:], start=start):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    block_end = i
                    break
        results.append((table_name, content[start:block_end + 1]))
    return results


def test_migrations_include_tenant_id() -> None:
    """Every CREATE TABLE in migration files must have a tenant_id column."""
    missing: list[str] = []

    for migration_file in sorted(MIGRATIONS_DIR.glob("*.py")):
        content = migration_file.read_text()
        for table_name, block in _extract_create_table_blocks(content):
            if table_name in SYSTEM_TABLES_ALLOWLIST:
                continue
            # Skip internal tracking tables
            if table_name.startswith("_"):
                continue
            if "tenant_id" not in block:
                missing.append(f"{migration_file.name}: {table_name}")

    assert not missing, (
        "Migrations that CREATE TABLE without tenant_id:\n"
        + "\n".join(f"  - {t}" for t in missing)
        + "\n\nEvery data table must include tenant_id. "
        "Add it or add the table to SYSTEM_TABLES_ALLOWLIST."
    )
