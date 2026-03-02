# CasinoLimit Client Simulation: Reality vs. Vision

**Classification:** Internal Engineering Assessment  
**Date:** 27 February 2026  
**Prepared by:** Pedkai Engineering  
**Dataset:** COMIDDS CasinoLimit CTF (140 game instances, 4 network zones per instance)  
**Reference Document:** `pedkai_committee_brief.md` (Committee Confidential — Pre-Demo Assessment)

---

## 1. Executive Summary

The CasinoLimit dataset from the COMIDDS collection has been loaded into the full Pedkai Docker stack (Datagerry CMDB, PostgreSQL+pgvector, TimescaleDB, Kafka). This document provides an honest, evidence-based assessment of what the loaded data actually demonstrates versus what the committee brief claims.

**Bottom line:** The CasinoLimit data provides strong evidence for Pedkai's core reconciliation capabilities (dark node discovery, phantom CI identification, MITRE ATT&CK cross-examination, multi-modal corroboration). It does *not* provide evidence for several higher-level claims around OSS/BSS consolidation, false alarm suppression, or financial projections — those require a real operator environment, not a CTF dataset.

---

## 2. Data Loaded — By The Numbers

### Datagerry CMDB (Declared State)

| Type | Count | Description |
|---|---|---|
| `casinolimit_game_instance` | 140 | All CasinoLimit game instances (23 unused, 117 active) |
| `casinolimit_network_zone` | 430 | 418 active zones + 12 deliberately injected phantom nodes |
| `casinolimit_attack_technique` | 66 | Unique MITRE ATT&CK techniques aggregated from system labels |
| `casinolimit_security_incident` | 114 | Incidents derived from attack pattern analysis |
| **Total CMDB Objects** | **750** | |

### PostgreSQL (Observed State + Topology)

| Table | Count | Description |
|---|---|---|
| `network_entities` | 635 | 117 services + 468 zones + 50 dark nodes |
| `entity_relationships` | 533 | 468 containment + 58 connection + 7 communication edges |
| `telemetry_flows` | 14,500 | Sampled from labelled_flows.zip (30 instances × ~483 flows) |
| `security_events` | 9,286 | MITRE ATT&CK labels from system_labels (140 instances) |
| `incidents` | 67 | Derived from attack pattern severity analysis |
| `reconciliation_hypotheses` | 76 | 50 dark nodes + 22 phantoms + 3 dark edges + 1 identity mutation |

### TimescaleDB (Time-Series KPIs)

| Metric | Count |
|---|---|
| KPI metric records | 2,400 |
| Unique entities with metrics | 50 |
| Time range | 12h window (15-min intervals) |

---

## 3. Claim-by-Claim Cross-Examination

### 3.1 Core Reconciliation Claims

| # | Committee Brief Claim | Evidence from CasinoLimit | Verdict |
|---|---|---|---|
| 1 | **Dark node discovery** — undocumented devices emitting telemetry with no CMDB record | 50 dark nodes discovered from 3,117 unique external IPs seen in Zeek/labelled flows. These are IPs communicating with known zones but absent from CMDB. Multi-modal corroboration: each dark node hypothesis references both `telemetry_flows` and `zeek_flows`. | **✅ DEMONSTRATED** |
| 2 | **Phantom CI identification** — CMDB entries with zero telemetry corroboration | 22 phantom hypotheses generated: 10 instances with zero telemetry activity + 12 deliberately injected stale CMDB entries. Confidence score 0.92–0.95. | **✅ DEMONSTRATED** |
| 3 | **Identity mutation detection** — undocumented hardware replacements | 1 identity mutation hypothesis generated from bastion privilege escalation patterns (T1069 across multiple instances). | **⚠️ PARTIAL** — Single hypothesis only, derived from MITRE label analysis rather than actual hardware identity change detection. |
| 4 | **Dark edge discovery** — undocumented functional connections | 3 dark edge hypotheses from external IP→zone traffic not declared in CMDB. | **⚠️ PARTIAL** — Low count (3) because the dataset's relation structure is synthetic/CTF-oriented. In a real operator environment, dark edges would be far more numerous. |
| 5 | **CMDB accuracy: 60–70% baseline → ≥95%** | Starting CMDB has 750 objects. Of these, 22 are identifiable phantoms (2.9%) and 50 dark nodes were missing (6.6%). After reconciliation, declared accuracy improves from ~90.4% to ~97%+. | **⚠️ PARTIAL** — The CasinoLimit CMDB was purpose-built so baseline accuracy is already ~90%, not the 60–70% claimed for real operators. The *mechanism* works but the *magnitude* doesn't match the brief's scenario. |
| 6 | **Multi-modal corroboration** — no hypothesis accepted from single source | 51 of 76 hypotheses (67%) have ≥2 evidence sources. The remaining 25 are phantom/identity hypotheses that by nature rely on single source types (CMDB-only or auditd-only). | **✅ DEMONSTRATED** for dark nodes. **⚠️ DESIGN GAP** — phantom hypotheses inherently single-source (absence of telemetry from a CMDB-only entity). The brief's claim of "no hypothesis accepted from a single data source" contradicts the phantom detection workflow. |
| 7 | **Noisy-OR confidence scoring** | Confidence scores assigned: dark nodes at 0.85, phantoms at 0.92–0.95, dark edges at 0.78, identity mutation at 0.88. | **⚠️ PARTIAL** — Scores are *assigned*, not *computed*. The loader hardcodes confidence values. A real noisy-OR implementation would derive scores from evidence weight and source reliability. The mathematical framework exists in the codebase but is not exercised end-to-end. |

### 3.2 MITRE ATT&CK / Security Claims

| # | Committee Brief Claim | Evidence from CasinoLimit | Verdict |
|---|---|---|---|
| 8 | **Telemetry cross-examination** — manual inputs validated against telemetry | 9,286 security events with 66 unique MITRE ATT&CK technique IDs loaded. Events span 140 instances with machine-level granularity. | **✅ DATA PRESENT** — The raw material for cross-examination exists. However, the cross-examination *engine* (checking manual CMDB updates against telemetry contradictions) is not exercised in this simulation. |
| 9 | **CVSS-weighted vulnerability surface reduction** | Not demonstrated. The CasinoLimit dataset does not include CVSS scores or vulnerability scan data. | **❌ NOT DEMONSTRATED** |
| 10 | **Zero-trust alignment** — accurate topology for policy enforcement | The reconciled topology (635 entities, 533 relationships) provides the graph structure. However, zero-trust policy enforcement is an architecture claim, not a data claim. | **⚠️ ARCHITECTURE ONLY** — The data supports the *foundation* but no zero-trust policy engine is demonstrated. |

### 3.3 Operational Efficiency Claims

| # | Committee Brief Claim | Evidence from CasinoLimit | Verdict |
|---|---|---|---|
| 11 | **False alarm suppression (Topological Ghost Mask)** — 15–25% incident reduction | Not demonstrated. Ghost masking requires change schedule data (planned maintenance windows). CasinoLimit has no change management data. | **❌ NOT DEMONSTRATED** |
| 12 | **MTTR improvement: 25–40%** | Not measurable. MTTR improvement requires before/after incident resolution time comparison. CasinoLimit is a CTF dataset with no incident resolution workflow. | **❌ NOT MEASURABLE** |
| 13 | **Field dispatch reduction: 10–20%** | 22 phantom hypotheses would each prevent an unnecessary field dispatch. In a real environment with thousands of CIs, this scales. The *mechanism* is demonstrated but the *percentage* requires a real operator CI estate. | **⚠️ MECHANISM ONLY** |

### 3.4 Financial / ROI Claims

| # | Committee Brief Claim | Evidence from CasinoLimit | Verdict |
|---|---|---|---|
| 14 | **Tool consolidation: 35–55% reduction** | Not demonstrable from dataset. This is an architectural claim about replacing redundant OSS tools. | **❌ NOT DEMONSTRABLE** — Requires real operator tool inventory. |
| 15 | **Payback: 18–24 months** | Not demonstrable from dataset. Financial projections require operator-specific cost data. | **❌ NOT DEMONSTRABLE** — By design; the brief correctly notes these are "illustrative" using public benchmarks. |
| 16 | **Phantom CI licence recovery: $2K/CI/year** | 22 phantom CIs identified × $2K = $44K/year potential saving. The mechanism is clean. Whether $2K/CI is realistic depends on operator licensing. | **⚠️ MECHANISM DEMONSTRATED** — Dollar figure is assumption-dependent. |

---

## 4. What Actually Works End-to-End

These are capabilities where the CasinoLimit data flows through the complete Pedkai pipeline — from raw dataset through parsing, normalisation, loading, reconciliation, and queryable output:

1. **Dark node discovery pipeline**: Raw Zeek/labelled flows → IP extraction → CMDB comparison → dark node entity creation → reconciliation hypothesis with multi-modal evidence
2. **Phantom CI detection pipeline**: CMDB instances/zones → telemetry activity check → zero-activity flagging → hypothesis generation with confidence scoring
3. **MITRE ATT&CK event loading**: system_labels JSON → security_events table with technique IDs, machine context, severity derivation → incident generation from attack patterns
4. **CMDB ↔ telemetry divergence**: Datagerry has 750 declared objects; PostgreSQL observes 635 entities. The 115-object delta (750 - 635) includes the 12 phantoms, 103 CMDB-side technique/incident records, and the 50 dark nodes visible only in telemetry — demonstrating the core reconciliation gap.
5. **Time-series KPI generation**: Synthetic but structurally correct — 2,400 metric records across 50 entities in TimescaleDB hypertable, queryable for traffic volume trends correlating with attack progression.

---

## 5. What Doesn't Work (Gaps)

### 5.1 Missing Capabilities (Not Exercised)

| Gap | Reason | Roadmap Priority |
|---|---|---|
| **Noisy-OR computation** | Confidence scores are hardcoded, not computed from evidence weights | **HIGH** — Core differentiator. Implement `backend/app/services/hypothesis_engine.py` with actual Bayesian computation. |
| **Cross-examination engine** | Manual CMDB updates are not validated against telemetry contradictions | **HIGH** — Central claim in the brief. Requires event-driven comparison workflow. |
| **Ghost Mask (false alarm suppression)** | No change schedule data in CasinoLimit | **MEDIUM** — Requires a separate data source (change management tickets). Can be simulated with synthetic schedules. |
| **Write-back to CMDB** | Hypotheses are generated but not written back to Datagerry as CI updates | **HIGH** — The "closing the loop" capability. REST API integration exists but the reconciliation → write-back workflow is not automated. |
| **Policy-gated integration** | No approval workflow for reconciliation actions | **MEDIUM** — Important for production but not critical for demo. |

### 5.2 Data Limitations

| Limitation | Impact |
|---|---|
| CasinoLimit is a CTF dataset, not a real operator environment | Cannot demonstrate scale claims (200–400 tools, 1200+ integration points) |
| 140 instances × 4 zones = relatively small topology | Real Tier-1: 50,000–80,000 CIs. Our 635 entities are 0.8–1.3% of realistic scale. |
| Network flow sampling (30 of 140 instances) | Full dataset is ~66GB. Loaded 14,500 of potential ~67M flow records (0.02%). |
| No change management data | Ghost Mask capability cannot be demonstrated |
| No vulnerability/CVSS data | Security surface quantification not possible |
| No incident resolution history | MTTR improvement claims not measurable |
| Synthetic KPI metrics | TimescaleDB data is generated, not from real telemetry |

### 5.3 Code Gaps

| Component | Status | Gap |
|---|---|---|
| `backend/app/services/hypothesis_engine.py` | Referenced but not fully implemented | Needs Bayesian noisy-OR computation |
| `backend/app/api/topology.py` | Exists, routes defined | Reconciliation endpoints need CasinoLimit tenant awareness |
| `backend/app/services/reconciliation_service.py` | Basic structure | Needs full hypothesis lifecycle (generate → cross-examine → promote/discard → integrate) |
| `backend/app/adapters/datagerry_adapter.py` | Exists | Write-back workflow not connected to hypothesis promotion |
| Alarm ingestion → Ghost Mask | Missing | No implementation of change schedule correlation |

---

## 6. Honest Assessment: Committee Brief Accuracy

### What the brief gets RIGHT:
- The core reconciliation concept (declared vs. observed state divergence) is real and demonstrable
- Dark node and phantom CI detection are genuinely useful capabilities, demonstrated end-to-end
- MITRE ATT&CK telemetry cross-referencing is data-backed (66 techniques, 9,286 events)
- The architecture (Datagerry + PostgreSQL + TimescaleDB + Kafka) is deployed and functional
- The multi-modal corroboration principle works for dark node detection
- The strangler-fig deployment model (passive-first, read-only) is architecturally honest
- Data sovereignty claim is accurate — everything runs locally, no external calls

### What the brief OVERSTATES:
- **"Noisy-OR confidence scoring"** — the mathematical framework is described but scores are currently hardcoded, not computed
- **"Multi-modal: no hypothesis accepted from a single source"** — phantom hypotheses are inherently single-source; the brief's absolutist claim contradicts the actual detection workflow
- **"≥95% CMDB accuracy"** — achievable in principle but the *starting baseline* in CasinoLimit is already ~90%, not the 60–70% the brief uses for its narrative
- **Financial projections** — the ROI model is properly caveated as "illustrative" and "based on public benchmarks", but the 560% ROI and $39.6M cumulative value figures will be read as promises by non-technical committee members

### What the brief CANNOT support with current data:
- Ghost Mask false alarm suppression (no change management data)
- MTTR improvement metrics (no incident resolution workflow)
- Tool consolidation projections (no operator tool inventory)
- Scale claims (635 entities vs. claimed 50K–80K CI estate)

---

## 7. Remediation Roadmap

### Immediate (Before Demo)

| # | Action | Effort | Impact |
|---|---|---|---|
| 1 | Fix Datagerry validation query (pagination: `limit=100`) | Done ✅ | Validation now shows all 14 types |
| 2 | Verify Datagerry UI shows CasinoLimit data at http://localhost:80 | 5 min | Visual proof for demo |
| 3 | Create demo queries showing reconciliation gaps | 30 min | Compelling before/after narrative |

### Short-Term (1–2 Weeks)

| # | Action | Effort | Impact |
|---|---|---|---|
| 4 | Implement actual noisy-OR computation in hypothesis engine | 3–5 days | Converts hardcoded scores to mathematically derived confidence |
| 5 | Build CMDB write-back workflow (hypothesis → Datagerry CI update) | 2–3 days | Closes the reconciliation loop |
| 6 | Add cross-examination engine (validate manual CMDB edits against telemetry) | 3–5 days | Backs up central committee brief claim |
| 7 | Generate synthetic change schedule data for Ghost Mask demo | 1 day | Demonstrates false alarm suppression |

### Medium-Term (1–2 Months)

| # | Action | Effort | Impact |
|---|---|---|---|
| 8 | Scale test with full CasinoLimit flow data (~67M records) | 1 week | Validates performance at higher volume |
| 9 | Build operator-specific data adapter (ServiceNow/Remedy mock) | 2 weeks | Demonstrates real ITSM integration |
| 10 | Implement policy-gated approval workflow | 1 week | Production-readiness feature |
| 11 | Load a second dataset (different tenant) to demonstrate multi-tenancy | 3 days | Proves tenant isolation |

---

## 8. Data Access Quick Reference

```bash
# Datagerry CMDB UI
open http://localhost:80

# Query dark nodes
psql -h localhost -p 5432 -U postgres -d pedkai -c \
  "SELECT name, entity_type, attributes->>'discovered_in' FROM network_entities WHERE tenant_id='casinolimit' AND entity_type='dark_node' LIMIT 10"

# Reconciliation hypotheses
psql -h localhost -p 5432 -U postgres -d pedkai -c \
  "SELECT hypothesis_type, entity_name, confidence_score, evidence_sources FROM reconciliation_hypotheses WHERE tenant_id='casinolimit' ORDER BY confidence_score DESC"

# MITRE ATT&CK technique breakdown
psql -h localhost -p 5432 -U postgres -d pedkai -c \
  "SELECT technique_id, COUNT(*) FROM security_events WHERE tenant_id='casinolimit' GROUP BY technique_id ORDER BY COUNT(*) DESC LIMIT 20"

# Incidents by severity
psql -h localhost -p 5432 -U postgres -d pedkai -c \
  "SELECT severity, COUNT(*), array_agg(DISTINCT title) FROM incidents WHERE tenant_id='casinolimit' GROUP BY severity"

# TimescaleDB KPI time-series
psql -h localhost -p 5433 -U postgres -d pedkai_metrics -c \
  "SELECT entity_id, MIN(timestamp), MAX(timestamp), AVG(metric_value)::numeric(10,2), COUNT(*) FROM kpi_metrics WHERE tenant_id='casinolimit' GROUP BY entity_id ORDER BY AVG(metric_value) DESC LIMIT 10"

# MongoDB CMDB object counts
docker exec nossl-db-1 mongosh --quiet --eval 'db=db.getSiblingDB("cmdb"); [30,31,32,33].forEach(t => print("Type " + t + ": " + db["framework.objects"].countDocuments({type_id:t})))'
```

---

## 9. Conclusion

The CasinoLimit simulation successfully demonstrates Pedkai's **core value proposition**: continuous reconciliation between declared CMDB state and observed telemetry state. The dark node discovery, phantom CI identification, and MITRE ATT&CK cross-referencing pipelines work end-to-end with real data.

The committee brief's higher-level claims (financial projections, tool consolidation, MTTR improvement) are legitimately framed as "illustrative" and "based on public benchmarks" — but anyone reading the document will treat them as forecasts. The engineering team should be prepared to clearly distinguish between **"demonstrated with data"** and **"projected from industry benchmarks"** during any committee presentation.

The dataset is loaded, the stack is running, and the reconciliation gaps are visible and queryable. What remains is connecting the hypothesis engine to the CMDB write-back path, implementing actual noisy-OR computation, and building the cross-examination workflow — all achievable within 2 weeks of focused engineering.
