"""
CX Intelligence Service.
Correlates network anomalies with customer churn risk for proactive care.
"""
import logging
from typing import List
from uuid import UUID
from sqlalchemy import select, and_, text
from backend.app.models.customer_orm import CustomerORM, ProactiveCareORM
from backend.app.models.decision_trace_orm import DecisionTraceORM

logger = logging.getLogger(__name__)

class CXIntelligenceService:
    def __init__(self, session):
        self.session = session

    async def identify_impacted_customers(self, anomaly_id: UUID) -> List[CustomerORM]:
        """
        Finds customers associated with a site experiencing an anomaly who have a high churn risk.
        Finding H-3: Implements multi-site correlation via simulated graph traversal.
        """
        # 1. Fetch the anomaly (DecisionTrace) to get the impacted entity/site
        trace = await self.session.get(DecisionTraceORM, anomaly_id)
        if not trace:
            logger.warning(f"Anomaly {anomaly_id} not found for CX correlation.")
            return []

        # Extract site ID from the trace
        site_id = trace.context.get("site_id") if trace.context else None
        
        # Finding H-9 FIX: Entity Inference for amorphous incidents
        if not site_id:
            logger.info(f"Anomaly {anomaly_id} lacks site_id. Attempting entity inference from affected_entities...")
            affected = trace.context.get("affected_entities", []) if trace.context else []
            if affected:
                # Try to find a parent node that acts as a site for any affected entity
                from backend.app.models.topology_models import EntityRelationshipORM
                
                inference_query = (
                    select(EntityRelationshipORM.from_entity_id)
                    .where(and_(
                        EntityRelationshipORM.to_entity_id.in_(affected),
                        EntityRelationshipORM.from_entity_type.in_(['site', 'router', 'aggregator'])
                    ))
                    .limit(1)
                )
                res = await self.session.execute(inference_query)
                inferred_node = res.scalar()
                if inferred_node:
                    site_id = inferred_node
                    logger.info(f"Inferred site_id {site_id} from affected entities {affected}")

        if not site_id:
            logger.warning(f"No specific site_id or inferrable parent found in anomaly {anomaly_id} context.")
            return []

        # Finding H-3 FIX: Real Recursive Graph Traversal
        # Traverse the topology to find the site and its downstream dependencies
        from sqlalchemy import text
        from backend.app.models.topology_models import EntityRelationshipORM
        
        # Recursive CTE to find all downstream entities (e.g., cells connected to a backhaul router)
        tenant_id = getattr(trace, "tenant_id", "default") or "default"
        recursive_query = text("""
            WITH RECURSIVE downstream_impact AS (
                SELECT to_entity_id, 1 AS depth
                FROM topology_relationships
                WHERE from_entity_id = :site_id AND tenant_id = :tid
                UNION ALL
                SELECT tr.to_entity_id, di.depth + 1
                FROM topology_relationships tr
                INNER JOIN downstream_impact di ON tr.from_entity_id = di.to_entity_id
                WHERE di.depth < :max_depth AND tr.tenant_id = :tid
            )
            SELECT DISTINCT to_entity_id FROM downstream_impact LIMIT 1000
        """)
        
        impacted_sites = [site_id]
        
        try:
            # Execute recursive query to get downstream dependencies
            res = await self.session.execute(recursive_query, {"site_id": site_id, "tid": tenant_id, "max_depth": 5})
            downstream = res.scalars().all()
            impacted_sites.extend(downstream)
            logger.info(f"Graph Traversal: Anomaly at {site_id} propagates to {len(downstream)} downstream nodes: {downstream}")
        except Exception as e:
            logger.error(f"Graph traversal failed: {e}. Falling back to single-site impact.")
        
        # 2. Query for customers matching any impacted site with churn risk > threshold
        # Finding H-6 FIX: Use Policy Engine parameters
        from backend.app.services.policy_engine import policy_engine
        churn_threshold = policy_engine.get_parameter("cx_churn_risk_alert_threshold", 0.70)
        
        query = select(CustomerORM).where(
            and_(
                CustomerORM.associated_site_id.in_(impacted_sites),
                CustomerORM.churn_risk_score > churn_threshold
            )
        )
        result = await self.session.execute(query)
        impacted = result.scalars().all()
        
        logger.info(f"Found {len(impacted)} high-risk customers impacted by anomaly at {site_id} (Checked {len(impacted_sites)} topological nodes)")
        return impacted

    async def trigger_proactive_care(self, customer_ids: List[UUID], anomaly_id: UUID) -> List[ProactiveCareORM]:
        """
        Mocks the sending of notifications to impacted customers.
        """
        records = []
        for cid in customer_ids:
            record = ProactiveCareORM(
                customer_id=cid,
                anomaly_id=anomaly_id,
                channel="simulation",
                status="sent",
                message_content="Proactive alert: We've detected an optimization event in your area. Coverage might be improved shortly."
            )
            records.append(record)
            self.session.add(record)
        
        await self.session.commit()
        logger.info(f"Triggered proactive care for {len(records)} customers linked to anomaly {anomaly_id}")
        return records
