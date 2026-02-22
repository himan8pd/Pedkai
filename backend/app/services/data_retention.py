"""
Data Retention Enforcement Service — Task 7.4 (Amendment #26)

Retention policies per DPIA (docs/dpia_scope.md):
  - KPI data:              30 days rolling
  - LLM prompt logs:       90 days
  - Incidents:             7 years (regulatory — NOT auto-deleted, archived only)
  - Audit trails:          7 years (regulatory — NOT auto-deleted, archived only)
  - Decision memory:       Indefinite (right-to-erasure via anonymisation)

Run daily via background task in main.py startup.
"""
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Tables eligible for automatic deletion (non-regulatory)
RETENTION_POLICIES: dict[str, timedelta] = {
    "kpi_metrics": timedelta(days=30),
    "llm_prompt_logs": timedelta(days=90),
}

# Tables with 7-year regulatory retention — NOT auto-deleted
# incidents, audit_event_log, incident_audit_entries — archived only
REGULATORY_TABLES = ["incidents", "audit_event_log", "incident_audit_entries"]


async def run_retention_cleanup(db: AsyncSession) -> dict:
    """
    Delete records older than their retention policy from non-regulatory tables.
    Safe to run daily as a scheduled background task.

    Returns a dict of {table_name: {"deleted": N, "cutoff": ISO timestamp}} per table.
    """
    results: dict = {}
    now = datetime.now(timezone.utc)

    for table, max_age in RETENTION_POLICIES.items():
        cutoff = now - max_age
        try:
            result = await db.execute(
                text(f"DELETE FROM {table} WHERE created_at < :cutoff"),  # noqa: S608
                {"cutoff": cutoff},
            )
            await db.commit()
            deleted = result.rowcount
            results[table] = {"deleted": deleted, "cutoff": cutoff.isoformat()}
            logger.info(
                f"Retention cleanup: deleted {deleted} rows from '{table}' "
                f"(cutoff: {cutoff.date()})"
            )
        except Exception as e:
            logger.error(f"Retention cleanup failed for '{table}': {e}")
            results[table] = {"error": str(e)}

    # Log regulatory tables as explicitly excluded
    for table in REGULATORY_TABLES:
        results[table] = {
            "skipped": True,
            "reason": "7-year regulatory retention — manual archival required",
        }

    return results


async def anonymise_customer(db: AsyncSession, customer_id: str) -> dict:
    """
    Anonymise a customer record for right-to-erasure (GDPR Art. 17).
    Does not delete the record — preserves referential integrity for 7-year incident records.

    Returns {"anonymised": True, "customer_id": customer_id} or {"error": ...}
    """
    try:
        await db.execute(
            text("""
                UPDATE customers
                SET msisdn_hash = NULL,
                    name        = '[REDACTED]',
                    email       = NULL,
                    phone       = NULL
                WHERE id = :cid
            """),
            {"cid": customer_id},
        )
        await db.commit()
        logger.info(f"Right-to-erasure: anonymised customer_id={customer_id}")
        return {"anonymised": True, "customer_id": customer_id}
    except Exception as e:
        logger.error(f"Anonymisation failed for customer_id={customer_id}: {e}")
        return {"error": str(e), "customer_id": customer_id}
