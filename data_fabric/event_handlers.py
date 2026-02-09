"""
Event Handlers for Kafka messages.

Processes incoming events and creates/updates decision traces.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from backend.app.models.decision_trace import (
    DecisionTraceCreate,
    DecisionContext,
    KPISnapshot,
    DecisionOutcome,
    DecisionOutcomeRecord,
)


async def handle_alarm_event(event_data: dict[str, Any]):
    """
    Handle incoming alarm events.
    
    Alarms can trigger decision-making processes.
    This handler logs the alarm and could trigger automated responses.
    """
    alarm_id = event_data.get("alarm_id")
    severity = event_data.get("severity", "unknown")
    description = event_data.get("description", "No description")
    affected_entity = event_data.get("affected_entity")
    
    print(f"🚨 Alarm received: {alarm_id} ({severity}) - {description}")
    
    # In a full implementation, this would:
    # 1. Check for similar past alarms and decisions
    # 2. Potentially trigger automated decision-making
    # 3. Create a decision trace based on the response
    
    return {
        "alarm_id": alarm_id,
        "processed_at": datetime.utcnow().isoformat(),
        "status": "received",
    }


async def handle_outcome_event(event_data: dict[str, Any]):
    """
    Handle decision outcome events.
    
    These events close the feedback loop by recording
    what happened after a decision was made.
    """
    decision_id = event_data.get("decision_id")
    status = event_data.get("status", "unknown")
    resolution_time = event_data.get("resolution_time_minutes")
    customer_impact = event_data.get("customer_impact_count", 0)
    learnings = event_data.get("learnings")
    
    print(f"📊 Outcome received for decision {decision_id}: {status}")
    
    # In a full implementation, this would:
    # 1. Update the decision trace with the outcome
    # 2. Trigger learning/model updates
    # 3. Update success metrics
    
    outcome = DecisionOutcomeRecord(
        status=DecisionOutcome(status) if status in DecisionOutcome.__members__ else DecisionOutcome.PENDING,
        resolution_time_minutes=resolution_time,
        customer_impact_count=customer_impact,
        learnings=learnings,
    )
    
    return {
        "decision_id": decision_id,
        "outcome_recorded": True,
        "processed_at": datetime.utcnow().isoformat(),
    }


from backend.app.core.database import get_metrics_db
from backend.app.core.config import get_settings
from anops.anomaly_detection import AnomalyDetector

settings = get_settings()

from anops.root_cause_analysis import RootCauseAnalyzer
from backend.app.services.llm_service import get_llm_service
from backend.app.services.decision_repository import DecisionTraceRepository
from backend.app.services.embedding_service import get_embedding_service
from backend.app.models.decision_trace import SimilarDecisionQuery, DecisionContext
from backend.app.core.database import get_db, get_metrics_db

async def handle_metrics_event(event_data: dict[str, Any]):
    """
    Handle incoming metrics/KPI events.
    
    Persists metrics to TimescaleDB and runs Anomaly Detection.
    If anomaly detected -> Trigger autonomous RCA and SITREP generation.
    """
    entity_id = event_data.get("entity_id")
    tenant_id = event_data.get("tenant_id", settings.default_tenant_id)
    metrics = event_data.get("metrics", {})
    timestamp = event_data.get("timestamp")
    
    print(f"📈 Metrics received for {entity_id}: {len(metrics)} values")
    
    results = []
    anomalies_found = []

    # 1. Process Metrics & Detect Anomalies (Hot Path - TimescaleDB)
    async for metrics_session in get_metrics_db():
        detector = AnomalyDetector(metrics_session)
        for metric_name, value in metrics.items():
            try:
                val = float(value)
                result = await detector.process_metric(
                    tenant_id=tenant_id,
                    entity_id=entity_id,
                    metric_name=metric_name,
                    value=val,
                    tags={"source": "kafka_consumer", "timestamp": timestamp}
                )
                results.append(result)
                if result["is_anomaly"]:
                    print(f"🚨 ANOMALY DETECTED: {entity_id} {metric_name}")
                    anomalies_found.append(metric_name)
            except Exception as e:
                print(f"❌ Error processing metric {metric_name}: {e}")

    # 2. Autonomous Reasoning Loop (Warm Path - Context Graph)
    # Only open Graph DB connection if anomalies were actually found
    if anomalies_found:
        # Import CausalAnalyzer here to run Granger Causality tests
        from anops.causal_analysis import CausalAnalyzer
        
        async for graph_session in get_db():
            try:
                # Service instantiation (efficiently reused logic)
                rca_service = RootCauseAnalyzer(graph_session)
                repo = DecisionTraceRepository(graph_session)
                llm_service = get_llm_service() # Use Singleton!
                embedding_service = get_embedding_service()
                
                print(f"🤖 Brain Activated: Investigating root cause for {entity_id}...")
                rca_results = await rca_service.analyze_incident(entity_id, tenant_id)
                
                # ===== CAUSAL AI: Granger Causality (Phase 2 Hardened) =====
                # We need a metrics session for causal analysis
                causal_evidence = []
                async for metrics_session_causal in get_metrics_db():
                    causal_analyzer = CausalAnalyzer(metrics_session_causal)
                    
                    for anomalous_metric in anomalies_found:
                        print(f"🔬 Running Hardened Granger Causality for {anomalous_metric}...")
                        # Finding #3: discovery is now dynamic inside find_causes_for_anomaly
                        causes = await causal_analyzer.find_causes_for_anomaly(
                            entity_id=entity_id,
                            anomalous_metric=anomalous_metric
                        )
                        causal_evidence.extend(causes)
                    
                    if causal_evidence:
                        for c in causal_evidence:
                            stationarity = " (Diffed)" if c.get("stationarity_fixed") else ""
                            print(f"   ✅ {c['cause_metric']} -> {c['effect_metric']}{stationarity} (p={c['p_value']})")
                    else:
                        print(f"   ⚠️ No valid causal relationships found (insufficient data or non-causal).")
                # ==========================================================
                
                # Check for similar decisions (Memory)
                search_text = f"Anomaly in {anomalies_found} for {entity_id}. RCA: {rca_results.get('upstream_dependencies')}"
                query_embedding = await embedding_service.generate_embedding(search_text)
                
                similar_decisions = []
                if query_embedding:
                    mock_query = SimilarDecisionQuery(
                        tenant_id=tenant_id,
                        current_context=DecisionContext(
                            alarm_ids=[f"ANOMALY_{m}" for m in anomalies_found],
                            affected_entities=[entity_id]
                        ),
                        limit=3,
                        min_similarity=0.7
                    )
                    similar_results = await repo.find_similar(mock_query, query_embedding)
                    similar_decisions = [d for d, _ in similar_results]
                
                # Generate SITREP (Intelligence) - Now with Causal Evidence!
                print(f"🧠 Synthesizing SITREP for {entity_id}...")
                sitrep = await llm_service.generate_explanation(
                    rca_results, 
                    similar_decisions,
                    causal_evidence=causal_evidence  # Pass causal evidence to LLM
                )
                
                print("\n==================== OPERATIONAL SITREP ====================")
                print(sitrep)
                print("============================================================\n")
                
            except Exception as e:
                 print(f"❌ Error in reasoning loop: {e}")
        
    return {
        "entity_id": entity_id,
        "metrics_processed": len(results),
        "anomalies_detected": len(anomalies_found),
        "processed_at": datetime.utcnow().isoformat(),
    }
