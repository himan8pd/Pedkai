"""
Data Retention Enforcement Service — Task 7.4 (Amendment #26)

PURPOSE: Ensures Pedkai does not retain customer-identifiable information
beyond mandated retention windows, and supports GDPR Article 17
right-to-erasure requests.

Pedkai ingests and processes telco customer data (names, identifiers,
location associations, behavioural scores) as part of its network
intelligence pipeline. This data is subject to:

  1. GDPR (General Data Protection Regulation) — right to erasure (Art. 17),
     purpose limitation (Art. 5(1)(b)), storage limitation (Art. 5(1)(e))
  2. Telco-specific regulations — customer confidentiality obligations under
     national telecom licences and ePrivacy Directive
  3. Internal DPIA (Data Protection Impact Assessment) — see docs/dpia_scope.md

Retention policies per DPIA:
  - KPI telemetry data:   30 days rolling (handled by TimescaleDB native policy)
  - LLM prompt logs:      90 days (auto-deleted by this service)
  - Incidents:            7 years (regulatory — NOT auto-deleted, archived only)
  - Audit trails:         7 years (regulatory — NOT auto-deleted, archived only)
  - Decision memory:      Indefinite (right-to-erasure via anonymisation)
  - Customer records:     Retained while active; anonymised on erasure request

IMPORTANT: When new PII-bearing columns are added to any ORM model, this
service MUST be updated. Reviewers should check data_retention.py in every
PR that modifies customer_orm.py, user_orm.py, or adds new tables with
customer-facing data.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.core.logging import get_logger

logger = get_logger(__name__)

# Tables eligible for automatic deletion (non-regulatory).
#
# NOTE: kpi_metrics retention is handled natively by TimescaleDB's
# add_retention_policy (30-day rolling, configured in init_db.py).
# Do NOT add kpi_metrics here — it lives on a separate DB instance
# (TimescaleDB :5433) and the graph DB session cannot reach it.
RETENTION_POLICIES: dict[str, timedelta] = {
    "llm_prompt_logs": timedelta(days=90),
}

# Different tables use different timestamp columns.
# kpi_metrics (TimescaleDB) uses 'timestamp'; most other tables use 'created_at'.
# This map allows the cleanup loop to use the correct column per table.
TIMESTAMP_COLUMN_OVERRIDES: dict[str, str] = {
    "kpi_metrics": "timestamp",
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

    async def run_retention_cleanup(
        self, session: Optional[AsyncSession] = None
    ) -> Dict:
        """
        Delete records older than their retention policy from non-regulatory tables.

        GDPR/DPIA compliance: enforce rolling retention windows.
        Different tables use different timestamp columns — see
        TIMESTAMP_COLUMN_OVERRIDES for overrides (default is 'created_at').
        """
        results: Dict = {}
        now = datetime.now(timezone.utc)

        async with self._get_session(session) as s:
            for table, max_age in RETENTION_POLICIES.items():
                cutoff = now - max_age
                ts_col = TIMESTAMP_COLUMN_OVERRIDES.get(table, "created_at")
                try:
                    result = await s.execute(
                        text(f"DELETE FROM {table} WHERE {ts_col} < :cutoff"),  # noqa: S608
                        {"cutoff": cutoff},
                    )
                    deleted = result.rowcount
                    results[table] = {"deleted": deleted, "cutoff": cutoff.isoformat()}
                    logger.info(
                        f"Retention cleanup: deleted {deleted} rows from '{table}' "
                        f"(cutoff: {cutoff.date()}, column: {ts_col})"
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

    async def anonymise_customer(
        self, customer_id: str, session: Optional[AsyncSession] = None
    ) -> Dict:
        """
        Anonymise a customer record for right-to-erasure (GDPR Art. 17).

        Pedkai processes telco customer data for network intelligence and must
        support right-to-erasure requests. This method irreversibly redacts all
        personally identifiable fields while preserving the row for referential
        integrity (billing accounts, proactive care records, topology associations
        all FK to customers.id).

        Fields redacted:
        - name:           Customer name → '[REDACTED]'
        - external_id:    Vendor customer ID (may encode PII such as MSISDN or
                          account number) → anonymised hash
        - churn_risk_score: Behavioural profile derived from PII → NULL
        - associated_site_id: Could reveal customer location → NULL

        Fields preserved (non-PII):
        - id:             Internal UUID (not customer-facing)
        - tenant_id:      Organisational grouping
        - created_at:     Record metadata

        Note: If the schema evolves to include additional PII columns (e.g. msisdn,
        email, phone, address), they MUST be added to this method. Review this
        method whenever CustomerORM is modified.
        """
        try:
            async with self._get_session(session) as s:
                await s.execute(
                    text("""
                        UPDATE customers
                        SET name              = '[REDACTED]',
                            external_id       = 'REDACTED-' || LEFT(md5(external_id::text), 12),
                            churn_risk_score  = NULL,
                            associated_site_id = NULL
                        WHERE id = :cid
                    """),
                    {"cid": customer_id},
                )
                logger.info(
                    f"GDPR right-to-erasure: anonymised customer_id={customer_id} "
                    f"(name, external_id, churn_risk_score, associated_site_id redacted)"
                )
                return {"anonymised": True, "customer_id": customer_id}
        except Exception as e:
            logger.error(
                f"GDPR anonymisation FAILED for customer_id={customer_id}: {e}"
            )
            return {"error": str(e), "customer_id": customer_id}
