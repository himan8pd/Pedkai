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

## Compliance Gaps & Status (Phase 3 Completed)

1. ✅ **AckState**: Added `ack_state` to `DecisionTraceORM` and Pydantic models. Exposed via `PATCH /alarm/{id}`.
2. ✅ **CorrelationId**: Implemented **Dual Correlation Strategy** (Strategic Review GAP 2):
   - `external_correlation_id`: Preservation of vendor-provided correlation ID.
   - `internal_correlation_id`: Pedkai RCA-calculated correlation ID (primary TMF reference).
3. ✅ **ProbableCause**: Added `probable_cause` to ORM. Mapped from vendor XML/JSON during normalization.

## Strategic Enhancements

- **REST Ingress (GAP 1)**: Added `POST /alarm` to allow legacy NMS tools (Nagios, etc.) to push alarms directly via REST if they cannot write to Kafka.
- **Security Scopes (GAP 3)**: Implemented OAuth2 scopes (`tmf642:alarm:read`, `tmf642:alarm:write`) to prevent unauthorized network control operations.
