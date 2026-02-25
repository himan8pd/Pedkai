"""
Data Retention Enforcement Service — Task 7.4 (Amendment #26)

Retention policies per DPIA (docs/dpia_scope.md):
  - KPI data:              30 days rolling
  - LLM prompt logs:       90 days
  - Incidents:             7 years (regulatory — NOT auto-deleted, archived only)
  - Audit trails:          7 years (regulatory — NOT auto-deleted, archived only)
  - Decision memory:       Indefinite (right-to-erasure via anonymisation)
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import text
from contextlib import asynccontextmanager
from backend.app.core.logging import get_logger

logger = get_logger(__name__)

# Tables eligible for automatic deletion (non-regulatory)
RETENTION_POLICIES: dict[str, timedelta] = {
    "kpi_metrics": timedelta(days=30),
    "llm_prompt_logs": timedelta(days=90),
}

# Tables with 7-year regulatory retention — NOT auto-deleted
REGULATORY_TABLES = ["incidents", "audit_event_log", "incident_audit_entries"]

class DataRetentionService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    @asynccontextmanager
    async def _get_session(self, session: Optional[AsyncSession] = None):
        if session:
            yield session
        else:
            async with self.session_factory() as new_session:
                try:
                    yield new_session
                    await new_session.commit()
                except Exception:
                    await new_session.rollback()
                    raise
                finally:
                    await new_session.close()

    async def run_retention_cleanup(self, session: Optional[AsyncSession] = None) -> Dict:
        """
        Delete records older than their retention policy from non-regulatory tables.
        """
        results: Dict = {}
        now = datetime.now(timezone.utc)

        async with self._get_session(session) as s:
            for table, max_age in RETENTION_POLICIES.items():
                cutoff = now - max_age
                try:
                    result = await s.execute(
                        text(f"DELETE FROM {table} WHERE created_at < :cutoff"),  # noqa: S608
                        {"cutoff": cutoff},
                    )
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

    async def anonymise_customer(self, customer_id: str, session: Optional[AsyncSession] = None) -> Dict:
        """
        Anonymise a customer record for right-to-erasure (GDPR Art. 17).
        """
        try:
            async with self._get_session(session) as s:
                await s.execute(
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
                logger.info(f"Right-to-erasure: anonymised customer_id={customer_id}")
                return {"anonymised": True, "customer_id": customer_id}
        except Exception as e:
            logger.error(f"Anonymisation failed for customer_id={customer_id}: {e}")
            return {"error": str(e), "customer_id": customer_id}
