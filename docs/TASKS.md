# Pedk.ai — Task Backlog

## Completed Tasks

### T-001: Consolidate Root-Level Documentation into Single Product Specification

**Priority:** Medium | **Status:** ✅ Done | **Completed:** 2026-03-05  
**Deliverable:** [`PRODUCT_SPEC.md`](file:///Users/himanshu/Projects/Pedk.ai/PRODUCT_SPEC.md)

---

## Open Tasks — Critical Priority 🔴

### T-003: Implement Behavioural Observation Feedback Pipeline
**Priority:** 🔴 Critical | **Status:** Open | **Created:** 2026-03-05  
Ingest operator ITSM actions (ticket modifications, CI interactions, resolution codes) as the primary learning signal. Behavioural observation is the highest quality feedback channel (see PRODUCT_SPEC.md §7).

### T-004: Improve Synthetic Data Realism
**Priority:** 🔴 Critical | **Status:** Open | **Created:** 2026-03-05 | **Project:** Sleeping-Cell-KPI-Data  
Address synthetic data quality risks: temporal patterns, propagation delays, CMDB decay calibration. Poor synthetic data → poor training → poor real-world performance.

### T-006: Write Substantive Regulatory Documents
**Priority:** 🔴 Critical | **Status:** Open | **Created:** 2026-03-05  
OFCOM pre-notification, ICO DPIA, Safety Whitepaper, Autonomy Status Report. Currently stubs. No customer engagement with OFCOM-regulated operators can proceed until these are substantive.

### T-016: Implement Abeyance Memory Decay and Cold Storage
**Priority:** 🔴 Critical | **Status:** Open | **Created:** 2026-03-05  
Abeyance Memory is Pedk.ai's core differentiator (§4). Requires: TTL with relevance weighting, cold storage retrieval pipeline, multi-modal matching (structured telemetry ↔ unstructured text).

### T-018: Replace UUID V4 with Operator-Realistic Identifiers
**Priority:** 🔴 Critical | **Status:** Open | **Created:** 2026-03-05 | **Project:** Sleeping-Cell-KPI-Data  
Real operators use human-friendly IDs (`LTE-8842-A`, `SITE-NW-1847`). Implement collision-safe naming conventions that match real-world patterns.

### T-024: Wire Sleeping Cell Detector into Scheduler
**Priority:** 🔴 Critical | **Status:** Open | **Created:** 2026-03-05  
`SleepingCellDetector` exists but is never started in `main.py`. Currently dead code. Wire into scheduler.

### T-025: Strengthen Dark Graph Module
**Priority:** 🔴 Critical | **Status:** Open | **Created:** 2026-03-05  
Complete Divergence Report generation, Datagerry adapter, CasinoLimit parser. Dark Graph is Pedk.ai's moat — this module must be ultra-strong.

---

## Open Tasks — High Priority 🟡

### T-029: Brand Definition & Styling for Pedk.ai
**Priority:** 🟡 High | **Status:** Open | **Created:** 2026-03-05  
Develop visual identity for the new "Pedk.ai" brand name. Requires: Typography selection (e.g., tech-forward sans-serif like Space Grotesk or Inter), logo mark (exploring network/node themes or lens/vision motifs emphasizing the ".ai" component), and CSS styling guide for the frontend dashboard.

### T-002: Formalise AI Behaviour Spec per Autonomy Level
**Priority:** 🟡 High | **Status:** Open | **Created:** 2026-03-05  
Define explicit behaviour specification for each autonomy level (0–3) from PRODUCT_SPEC.md §7.

### T-005: Implement Continuous Evaluation Pipeline
**Priority:** 🟡 High | **Status:** Open | **Created:** 2026-03-05  
Business outcome linkage for decision quality tracking.

### T-007: Implement Structured Multi-Dimensional Operator Assessment
**Priority:** 🟡 High | **Status:** Open | **Created:** 2026-03-05  
Multi-dimensional assessment forms (accuracy, relevance, actionability) integrated into NOC dashboard.

### T-008: Implement Persistent Event Bus
**Priority:** 🟡 High | **Status:** Open | **Created:** 2026-03-05  
Replace in-process asyncio.Queue with Redis-backed queue for production resilience.

### T-009: Design Reference Deployment Scenario
**Priority:** 🟡 High | **Status:** Open | **Created:** 2026-03-05  
Advisory-only mode reference deployment to prove value before any automation is offered.

### T-010: Validate Training Curriculum with Pilot NOC Team
**Priority:** 🟡 High | **Status:** Open | **Created:** 2026-03-05  
Test training materials with real operators using synthetic data exercises.

### T-017: Implement FusionMethodologyFactory
**Priority:** 🟡 High | **Status:** Open | **Created:** 2026-03-05  
Pluggable evidence fusion: Noisy-OR (V1), Dempster-Shafer (V2). See PRODUCT_SPEC.md §5.

### T-019: Validate Synthetic Fault Scenarios
**Priority:** 🟡 High | **Status:** Open | **Created:** 2026-03-05 | **Project:** Sleeping-Cell-KPI-Data  
Compare synthetic fault injection patterns against published Tier-1 post-incident reports.

### T-020: Implement Diurnal/Seasonal Temporal Patterns
**Priority:** 🟡 High | **Status:** Open | **Created:** 2026-03-05 | **Project:** Sleeping-Cell-KPI-Data  
Replace pure AR(1) with empirical distribution sampling reflecting real network temporal patterns.

### T-021: Add Propagation Delay Profiles
**Priority:** 🟡 High | **Status:** Open | **Created:** 2026-03-05 | **Project:** Sleeping-Cell-KPI-Data  
Configurable delay profiles per domain boundary for more realistic cascading alarm scenarios.

### T-022: Calibrate CMDB Degradation Rates
**Priority:** 🟡 High | **Status:** Open | **Created:** 2026-03-05 | **Project:** Sleeping-Cell-KPI-Data  
Calibrate against published CMDB audit statistics from industry reports.

### T-023: Add Causal Inference Alternatives
**Priority:** 🟡 High | **Status:** Open | **Created:** 2026-03-05  
Add Transfer Entropy and PCMCI alongside Granger Causality. See PRODUCT_SPEC.md §8.

### T-026: Abeyance Memory Multi-Modal Matching
**Priority:** 🟡 High | **Status:** Open | **Created:** 2026-03-05  
Structured telemetry ↔ unstructured text alignment for cross-modality evidence snapping.

### T-027: Frontend Decomposition
**Priority:** 🟡 High | **Status:** Open | **Created:** 2026-03-05  
Split monolithic `page.tsx` (496 lines) into separate routed pages per roadmap requirement.

### T-028: Phase 5 Test Suite Expansion
**Priority:** 🟡 High | **Status:** Open | **Created:** 2026-03-05  
Expand from ~5 trivial tests to comprehensive safety gate coverage for autonomous execution.

---

## Open Tasks — Medium Priority 🟢

### T-030: Topology Data Improvement (Telco2)
**Priority:** 🟢 Medium | **Status:** Open | **Created:** 2026-03-05
Significant improvement needed for Telco2 topology data appearing in the system. Details to be provided by user.

### T-011: Define AI-Adjusted NOC Engineer Role Spec
**Priority:** 🟢 Medium | **Status:** Open | **Created:** 2026-03-05

### T-012: Build Hands-On Training Environment
**Priority:** 🟢 Medium | **Status:** Open | **Created:** 2026-03-05  
Using Sleeping-Cell-KPI-Data synthetic data for practical operator training exercises.

### T-013: Design Cross-Team SITREP Escalation Workflow
**Priority:** 🟢 Medium | **Status:** Open | **Created:** 2026-03-05

### T-014: Implement Automated Playbook Generation
**Priority:** 🟢 Medium | **Status:** Open | **Created:** 2026-03-05  
Generate operational playbooks from high-confidence Decision Memory patterns.

### T-015: Create Operator-Facing "Pedk.ai Learning Hub"
**Priority:** 🟢 Medium | **Status:** Open | **Created:** 2026-03-05