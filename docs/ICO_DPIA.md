# ICO Data Protection Impact Assessment (DPIA) — Pedkai Autonomous Execution

## Data Flows
- Decision traces: stored with pseudonymous operator identifiers and trace_id
- Incident telemetry: KPIs and alarms retained per tenant policy
- Audit logs: retained for 12 months (configurable)

## Privacy Risks
- Operator feedback contains PII → use hashed operator IDs for storage
- Cross-tenant contamination risk mitigated via tenant-scoped policies and DB filters

## Mitigations
- Role-based access controls
- Retention policy and automated purge
- DPIA review for OFCOM submission

Prepared by: Legal & Data Protection Office
