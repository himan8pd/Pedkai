"""Migrate incidents to ITIL v4 priority matrix: add impact, urgency, priority columns."""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/pedkai"

MAPPING = {
    # severity -> (impact, urgency, priority)
    "critical": ("high", "high", "P1"),       # P1 Critical
    "high":     ("high", "medium", "P2"),      # P2 High
    "major":    ("high", "medium", "P2"),      # P2 High
    "medium":   ("medium", "medium", "P3"),    # P3 Medium
    "minor":    ("medium", "low", "P3"),       # P3 Medium
    "warning":  ("low", "medium", "P4"),       # P4 Low
}

async def main():
    engine = create_async_engine(DB_URL)
    async with engine.connect() as conn:
        # 1. Add columns
        for col in ("impact", "urgency", "priority"):
            await conn.execute(text(
                f"ALTER TABLE incidents ADD COLUMN IF NOT EXISTS {col} VARCHAR(20)"
            ))

        # 2. Map existing severity values
        for sev, (imp, urg, pri) in MAPPING.items():
            await conn.execute(text(
                "UPDATE incidents SET impact=:imp, urgency=:urg, priority=:pri "
                "WHERE severity=:sev"
            ), {"imp": imp, "urg": urg, "pri": pri, "sev": sev})

        # 3. Catch-all for any unmapped rows
        await conn.execute(text(
            "UPDATE incidents SET impact='medium', urgency='medium', priority='P3' "
            "WHERE priority IS NULL"
        ))

        await conn.commit()

        # 4. Verify
        r = await conn.execute(text(
            "SELECT priority, impact, urgency, count(*) "
            "FROM incidents GROUP BY priority, impact, urgency ORDER BY priority"
        ))
        print("ITIL Priority Distribution:")
        for row in r.fetchall():
            print(f"  {row[0]}: impact={row[1]}, urgency={row[2]}, count={row[3]}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
