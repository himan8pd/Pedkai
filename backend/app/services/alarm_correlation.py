"""
Alarm Correlation Service.

Adds business context to pre-correlated alarms from OSS vendor systems.
This service does NOT replace vendor correlation engines (e.g., Nokia NetAct, Ericsson ENM).
It consumes their output and enriches it with topology proximity, temporal clustering,
and business impact (revenue-at-risk, emergency service detection).

Used by: WS4 (service_impact API router).
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, text
from contextlib import asynccontextmanager

from backend.app.schemas.service_impact import AlarmCluster, CustomerImpact, ServiceImpactSummary

logger = logging.getLogger(__name__)

# Temporal clustering window: alarms within this window are candidates for grouping
TEMPORAL_WINDOW_MINUTES = 5


class AlarmCorrelationService:
    """
    Enriches pre-correlated OSS alarms with business context.

    Positioning: This service consumes pre-correlated alarms from OSS and adds
    business context (revenue-at-risk, emergency service escalation, customer impact).
    It does not replace vendor correlation engines.
    """

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

    def correlate_alarms(self, alarms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Optimized O(n log n) alarm correlation using sorting and spatial partitioning.

        Strategy (replaces O(n²) nested loop):
        1. Parse timestamps and normalize alarms (O(n))
        2. Group by entity_id (O(n))
        3. Sort within each group by raised_at (O(k log k) per group)
        4. Merge temporally adjacent alarms within same entity (O(k) per group)
        5. Cross-entity merge for same alarm_type with temporal overlap (O(m log m) where m = num groups)

        Returns list of cluster dicts with same format as before.
        """
        if not alarms:
            return []

        # Step 0: Parse all timestamps and normalize
        normalized_alarms = []
        for alarm in alarms:
            time = self._parse_time(alarm.get("raised_at"))
            normalized_alarms.append((alarm, time))

        # Step 1: Group by entity_id (O(n))
        entity_groups: Dict[Any, List[tuple]] = {}
        for alarm, time in normalized_alarms:
            entity_id = alarm.get("entity_id")
            if entity_id not in entity_groups:
                entity_groups[entity_id] = []
            entity_groups[entity_id].append((alarm, time))

        # Step 2: Sort within each group by raised_at (O(k log k))
        for entity_id in entity_groups:
            entity_groups[entity_id].sort(
                key=lambda x: x[1] if x[1] else datetime.max
            )

        # Step 3: Create initial clusters within each entity using temporal window
        proto_clusters: List[List[Dict[str, Any]]] = []
        for entity_id, group in entity_groups.items():
            current_cluster: List[Dict[str, Any]] = []
            last_time: Optional[datetime] = None

            for alarm, time in group:
                if not current_cluster:
                    # Start new cluster
                    current_cluster = [alarm]
                    last_time = time
                else:
                    # Check if within temporal window
                    within_window = False
                    if time and last_time:
                        diff = abs((time - last_time).total_seconds())
                        within_window = diff <= TEMPORAL_WINDOW_MINUTES * 60
                    elif not time or not last_time:
                        # If no time data, keep clustering
                        within_window = True

                    if within_window:
                        current_cluster.append(alarm)
                        if time:
                            last_time = time
                    else:
                        # Finalize current cluster and start new one
                        if current_cluster:
                            proto_clusters.append(current_cluster)
                        current_cluster = [alarm]
                        last_time = time

            # Add final cluster
            if current_cluster:
                proto_clusters.append(current_cluster)

        # Step 4: Merge proto-clusters across entities with same alarm_type and temporal overlap
        # Group proto-clusters by alarm_type
        type_groups: Dict[Optional[str], List[List[Dict[str, Any]]]] = {}
        for cluster in proto_clusters:
            alarm_type = cluster[0].get("alarm_type") if cluster else None
            if alarm_type not in type_groups:
                type_groups[alarm_type] = []
            type_groups[alarm_type].append(cluster)

        # Merge clusters of same type with temporal overlap
        final_clusters: List[List[Dict[str, Any]]] = []
        processed_clusters: set = set()

        for alarm_type, type_clusters in type_groups.items():
            for i, cluster_i in enumerate(type_clusters):
                cluster_key_i = (alarm_type, i)
                if cluster_key_i in processed_clusters:
                    continue

                # Start with cluster_i
                merged = list(cluster_i)
                processed_clusters.add(cluster_key_i)

                # Only attempt cross-entity merge if alarm_type is defined
                # (i.e., NOT None). This preserves entity boundaries when alarm_type info is missing.
                if alarm_type is not None:
                    # Get time range of cluster_i
                    times_i = [self._parse_time(a.get("raised_at")) for a in cluster_i]
                    times_i = [t for t in times_i if t is not None]

                    if times_i:
                        min_time_i = min(times_i)
                        max_time_i = max(times_i)

                        # Try to merge other clusters of same type with temporal overlap
                        for j, cluster_j in enumerate(type_clusters):
                            cluster_key_j = (alarm_type, j)
                            if cluster_key_j in processed_clusters or j <= i:
                                continue

                            times_j = [self._parse_time(a.get("raised_at")) for a in cluster_j]
                            times_j = [t for t in times_j if t is not None]

                            if times_j:
                                min_time_j = min(times_j)
                                max_time_j = max(times_j)

                                # Check for temporal overlap within extended window
                                window_delta = timedelta(minutes=TEMPORAL_WINDOW_MINUTES)
                                if (min_time_i <= max_time_j + window_delta and
                                    min_time_j <= max_time_i + window_delta):
                                    merged.extend(cluster_j)
                                    processed_clusters.add(cluster_key_j)

                if merged:
                    final_clusters.append(merged)

        # Step 5: Convert to output format
        clusters: List[Dict[str, Any]] = []
        for cluster_alarms in final_clusters:
            if not cluster_alarms:
                continue

            # Determine cluster severity
            severities = [a.get("severity", "minor") for a in cluster_alarms]
            cluster_severity = self._highest_severity(severities)

            # Check for emergency service
            is_emergency = any(
                a.get("entity_type") == "EMERGENCY_SERVICE" or a.get("is_emergency_service")
                for a in cluster_alarms
            )
            if is_emergency:
                cluster_severity = "critical"

            # Determine root cause entity (most frequent entity in cluster)
            entity_ids = [a.get("entity_id") for a in cluster_alarms if a.get("entity_id")]
            root_entity_id = max(set(entity_ids), key=entity_ids.count) if entity_ids else None

            clusters.append({
                "alarm_count": len(cluster_alarms),
                "alarms": cluster_alarms,
                "severity": cluster_severity,
                "is_emergency_service": is_emergency,
                "root_cause_entity_id": root_entity_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

        return clusters

    def calculate_noise_reduction(self, raw_count: int, clustered_count: int) -> float:
        """
        Calculate the noise reduction percentage.
        e.g., 100 raw alarms → 10 clusters = 90% reduction.
        """
        if raw_count == 0:
            return 0.0
        reduction = ((raw_count - clustered_count) / raw_count) * 100.0
        return round(max(0.0, min(100.0, reduction)), 2)

    async def get_customer_impact(self, cluster_entity_ids: List[str], tenant_id: str, session: Optional[AsyncSession] = None) -> List[Dict[str, Any]]:
        """
        Traverse topology to find customers impacted by the given entity IDs.
        Queries the topology_entities and customers tables with strict tenant isolation.
        """
        if not cluster_entity_ids:
            return []

        impacted_customers = []
        try:
            async with self._get_session(session) as s:
                # Finding S-1 Fix: Enforce tenant isolation
                query = text("""
                    SELECT c.id, c.name, c.external_id, c.tenant_id
                    FROM customers c
                    WHERE c.associated_site_id IN :site_ids
                    AND c.tenant_id = :tid
                """)
                result = await s.execute(query, {"site_ids": tuple(cluster_entity_ids), "tid": tenant_id})
                rows = result.fetchall()
                for row in rows:
                    impacted_customers.append({
                        "customer_id": str(row[0]),
                        "customer_name": row[1] or "Unknown",
                        "customer_external_id": row[2] or str(row[0]),
                        "tenant_id": row[3],
                    })
        except Exception as e:
            logger.warning(f"Could not fetch customer impact: {e}")

        return impacted_customers

    def _parse_time(self, time_val: Any) -> Optional[datetime]:
        """Parse a time value to datetime."""
        if isinstance(time_val, datetime):
            return time_val
        if isinstance(time_val, str):
            try:
                return datetime.fromisoformat(time_val.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    def _highest_severity(self, severities: List[str]) -> str:
        """Return the highest severity from a list."""
        order = {"critical": 4, "major": 3, "minor": 2, "warning": 1}
        return max(severities, key=lambda s: order.get(s, 0), default="minor")
