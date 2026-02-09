# TMF642 Alarm Management Mapping

To ensure Pedkai's "Decision Intelligence" can integrate with existing telecom operations, we map our `DecisionTrace` model to the **TM Forum TMF642** standard.

## Core Mapping Table

| Pedkai DecisionTrace Field | TMF642 Alarm Attribute | Rationale |
| :--- | :--- | :--- |
| `id` | `id` | Unique identifier for the trace/alarm. |
| `trigger_description` | `description` | Textual details of what triggered the event. |
| `trigger_type` | `alarmType` | Map 'alarm' -> 'CommunicationsAlarm', 'threshold' -> 'QualityOfServiceAlarm', etc. |
| `decision_summary` | `specificProblem` | High-level summary of the issue identified by the intelligence. |
| `tradeoff_rationale` | `comment` | Detailed internal notes on why a specific action was chosen. |
| `action_taken` | `proposedRepairAction`| What the automation (or human) did to resolve it. |
| `confidence_score` | `perceivedSeverity` | High confidence + critical anomaly -> 'Critical'. Low confidence -> 'Warning'. |
| `created_at` | `eventTime` | When the anomaly/trigger was first detected. |
| `decision_made_at` | `raisedTime` | When the system completed its analysis and made a decision. |
| `outcome.status` | `state` | 'success' -> 'Cleared', 'failed' -> 'Raised/Error'. |
| `context.affected_entities`| `impactedResource` | List of UUIDs/Hrefs of the network nodes affected. |

## Severity Mapping Logic

Pedkai maps its `confidence_score` (0-1) and `anomaly_score` (z-score) to TMF `perceivedSeverity` as follows:

- **Critical**: Anomaly Score > 10 OR (Confidence > 0.9 AND Priority=High)
- **Major**: Anomaly Score 5-10
- **Minor**: Anomaly Score 3-5
- **Warning**: Anomaly Score < 3 (Suspicious behavior)
- **Indeterminate**: System is unsure, requires human in the loop.

## Compliance Gaps & Recommendations

1. **AckState**: Pedkai doesn't yet have a human-acknowledgment state. We should add `ackState` to `DecisionTrace` to capture when a NOC engineer accepts the system's recommendation.
2. **CorrelationId**: We should expose our `CorrelationId` (if multi-anomaly) to TMF to allow legacy NMS to group Pedkai-detected events.
3. **ProbableCause**: Pedkai's RCA output should be mapped to the TMF enumerated list of probable causes (e.g., `thresholdCrossed`, `equipmentFailure`).
