# Pedkai — Ofcom Pre-Notification: AI-Assisted Network Operations

**Document ID**: PEDKAI-OFCOM-PN-001
**Version**: 1.0
**Classification**: Confidential — Regulatory
**Date**: 2026-02-25
**Recipient**: Ofcom — Networks & Communications Group

---

## 1. Purpose

This document constitutes voluntary pre-notification to Ofcom regarding the deployment of AI-assisted network operations capabilities by [Operator Name] using the Pedkai platform. Pre-notification is provided in the spirit of regulatory transparency per General Conditions §A.3 (network reliability) and the Ofcom Statement on AI in Telecoms (2025).

## 2. Scope of AI Deployment

### 2.1 Capabilities Deployed

| Capability | Description | AI Role | Human Oversight |
|-----------|-------------|---------|-----------------|
| Alarm Correlation | Groups related alarms into incidents | Automated clustering | Human reviews clusters |
| SITREP Generation | Natural language incident summaries | AI-generated (Gemini) | Human approval required |
| Drift Detection | Predictive KPI anomaly detection | AI prediction | Human acts on recommendations |
| Service Impact Analysis | Revenue-at-risk calculation | Data aggregation | All figures flagged if estimated |
| Sleeping Cell Detection | Identifies silent network degradation | Automated scan | Human investigates alerts |

### 2.2 Capabilities NOT Deployed

- No autonomous network reconfiguration without human approval
- No automated customer communication
- No AI-driven capacity changes without human sign-off

## 3. Safety Controls

Pedkai implements a four-gate safety pipeline for any prospective autonomous action:

1. **Blast Radius Limit**: Actions affecting >10 network entities are automatically rejected
2. **Policy Engine**: Operator-configurable rules gate all actions
3. **Confirmation Window**: Minimum 30-second human override window
4. **Post-Execution Validation**: 5-minute KPI monitoring with automatic rollback on >10% degradation

An emergency kill-switch is available to immediately roll back recent autonomous actions.

## 4. Consumer Impact Assessment

- **Service Continuity**: AI recommendations are advisory; network operations remain under human control. No consumer-facing changes are made autonomously.
- **Emergency Services**: The platform flags entities serving emergency services (`is_emergency_service`) and applies enhanced scrutiny to any actions affecting them.
- **Customer Privacy**: Customer billing data is processed locally with GDPR-compliant PII scrubbing. AI models do not have direct access to customer personal data.

## 5. Transparency Measures

- All AI-generated content is watermarked with origin, model version, and advisory disclaimer
- Revenue figures carry `is_estimate` flags when derived from estimated data
- Full audit trail maintained for all automated decisions with correlation IDs

## 6. Monitoring and Reporting

- Quarterly safety reports submitted to [Operator Name] Board
- Incident reports for any AI-related service impacts within 24 hours
- Annual review of AI maturity level progression
- All KPI drift false positive rates tracked and calibrated monthly

## 7. Contact

For regulatory queries regarding this pre-notification:
- **Technical Contact**: Platform Architecture Team
- **Regulatory Contact**: [Operator Name] Regulatory Affairs
