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


async def handle_metrics_event(event_data: dict[str, Any]):
    """
    Handle incoming metrics/KPI events.
    
    These provide context for decision-making.
    """
    entity_id = event_data.get("entity_id")
    metrics = event_data.get("metrics", {})
    
    print(f"📈 Metrics received for {entity_id}: {len(metrics)} values")
    
    # Store as KPI snapshot for decision context
    snapshot = KPISnapshot(
        throughput_mbps=metrics.get("throughput_mbps"),
        latency_ms=metrics.get("latency_ms"),
        packet_loss_pct=metrics.get("packet_loss_pct"),
        availability_pct=metrics.get("availability_pct"),
        cpu_utilization_pct=metrics.get("cpu_utilization_pct"),
        memory_utilization_pct=metrics.get("memory_utilization_pct"),
        custom_metrics=metrics,
    )
    
    return {
        "entity_id": entity_id,
        "snapshot_created": True,
        "processed_at": datetime.utcnow().isoformat(),
    }
