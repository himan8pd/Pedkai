# ADR-001: Autonomy Positioning Decision

## Status
Proposed (Gates Phase 4 Scope)

## Context
There is currently a divergence between the Pedkai **demo narrative** (which suggests autonomous execution of network repairs and optimizations) and the **code reality** (which is strictly advisory, requiring human intervention for every action). This document resolves this conflict and defines the target state for Phase 4.

## Options

### Option A: Advisory-only (Current State)
The system identifies issues and recommends actions via SITREPs and the Autonomous Shield dashboard, but never executes them directly.
- **Benefits**:
    - Zero risk of unintended automated network-wide outages.
    - No complex safety-gate policy engine required.
    - Faster initial speed to market for decision intelligence.
- **Risks**:
    - Lower operational efficiency; human-in-the-loop becomes a bottleneck.
    - Fails to meet "Self-Healing Network" product vision.
    - Competitive disadvantage against 100% autonomous platforms.

### Option B: Advisory with Opt-in Auto-execution (Recommended)
Allow specific, low-risk actions or specific tenants to opt-in to autonomous execution, subject to Phase 4 Safety Gates.
- **Benefits**:
    - Progressive path to full autonomy.
    - Risk is managed per-tenant and per-action-type.
    - Aligns with the "Autonomous Shield" concept (Safety First).
- **Risks**:
    - Requires significant investment in the Policy Engine (Phase 4).
    - Requires robust "circuit breakers" and roll-back capabilities.
- **Dependencies**: Completion of Phase 4 (Policy Engine Hardening).

### Option C: Autonomous-first
All recommendations are executed by default unless explicitly blocked by a human or policy.
- **Benefits**:
    - Maximum network efficiency and response time.
    - Purest realization of the AI-Native OS vision.
- **Risks**:
    - Extremely high risk of catastrophic failure without mature safety-gates.
    - Requires complete internal culture shift and regulatory approval in some regions.
    - Likely requires a separate specialized product for mission-critical infrastructure.

## Decision
Pending Product Owner and CTO sign-off.

## Risk Assessment Matrix

| Option | Stability Risk | Implementation Complexity | Market Value |
| :--- | :--- | :--- | :--- |
| **A** | Low | Low | Medium |
| **B** | Medium | High | High |
| **C** | High | Very High | High |

## Sign-off Required

| Role | Name | Signature | Date |
| :--- | :--- | :--- | :--- |
| Product Owner | | | |
| CTO | | | |
