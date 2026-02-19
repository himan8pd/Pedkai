# Pedkai Committee Reassessment — Source Code Audit

**Date**: 18 February 2026  
**Review Body**: Full Executive Committee (14 members)  
**Scope**: Exhaustive line-by-line audit of all source code, configuration, and test coverage  
**Methodology**: Every finding below is derived from direct code inspection — no reliance on vendor claims, `.md` files, or walkthrough documents  

---

## Overall Verdict: SIGNIFICANT CONCERNS REMAIN — Conditional Approval Rescinded Pending Remediation

The vendor has addressed a subset of our 26 mandatory amendments. However, the committee's direct source code audit reveals **critical security breaches, architectural dead-ends, fabricated metrics, and integration gaps** that were not visible in the vendor's self-reported documentation. Several issues are new regressions introduced by the vendor's own remediation work. This reassessment is blunt because the vendor needs actionable, unambiguous direction.

---

## Part 1: BLOCKER-Grade Findings (Must Be Fixed Before Any Demo or Pilot)

---

### 🔴 B-1: LIVE API KEYS AND PASSWORDS COMMITTED TO GIT

**Severity**: 🔴 CRITICAL — Immediate Credential Rotation Required  
**Files**: [.env](file:///Users/himanshu/Projects/Pedkai/.env)

The `.env` file contains **live, working credentials** and is present in the repository:

```
GEMINI_API_KEY=[redacted]    # Line 22
HF_TOKEN=[redacted]           # Line 37
KAGGLE_USERNAME=[redacted]                                     # Line 41
KAGGLE_KEY=[redacted]            # Line 42
SECRET_KEY=[redacted]   # Line 45
ADMIN_PASSWORD=[redacted]                              # Line 46
OPERATOR_PASSWORD=[redacted]                        # Line 47
```

While `.gitignore` lists `.env` (line 41), the file is already tracked and present in the working tree. This means:
- All API keys must be **rotated immediately** — they are compromised
- `SECRET_KEY` is used to sign JWTs ([security.py:87](file:///Users/himanshu/Projects/Pedkai/backend/app/core/security.py#L87)). Anyone with this key can forge admin tokens
- The `SECRET_KEY` value is literally `demo-secret-key-insecure-only-for-local-playpen` — a predictable string

**Action Required**:
1. Run `git rm --cached .env` to untrack the file
2. Rotate ALL credentials (Gemini, HuggingFace, Kaggle, passwords)
3. Use a secrets manager (e.g., GCP Secret Manager, AWS Secrets Manager) instead of plain environment variables for production
4. Generate `SECRET_KEY` with `openssl rand -hex 32` at deployment time

---

### 🔴 B-2: PII SCRUBBER EXISTS BUT IS NEVER CALLED — LLM DATA LEAKAGE IS LIVE

**Severity**: 🔴 CRITICAL — Our §2.8 (Security Director) Mandate Unaddressed  
**Files**:  
- [pii_scrubber.py](file:///Users/himanshu/Projects/Pedkai/backend/app/services/pii_scrubber.py) — well-implemented, 143 lines  
- [llm_service.py](file:///Users/himanshu/Projects/Pedkai/backend/app/services/llm_service.py) — the file that sends prompts to Gemini  

The vendor built a fully functional `PIIScrubber` class with regex patterns for UK/US phone numbers, IMSI, subscriber names, billing amounts, account numbers, and IPv4 addresses. **However, it is never imported or used in `llm_service.py`.**

Our `grep_search` confirms: **zero references to `PIIScrubber` or `pii_scrubber` in `llm_service.py`**. The scrubber is only exercised by a unit test (`tests/unit/test_pii_scrubber.py`).

This means **every** call to `generate_explanation()` sends raw network topology data, customer names, billing amounts, and IP addresses **directly to Google Gemini's API** — exactly the data exfiltration risk our Security Director flagged in §2.8.

Look at the prompt construction in [llm_service.py:207-235](file:///Users/himanshu/Projects/Pedkai/backend/app/services/llm_service.py#L207-L235):
```python
prompt = f"""
You are Pedkai, an AI-Native Telco Operator.
[NETWORK EVENT]
{json.dumps(incident_context, indent=2)}    # <-- RAW incident data with customer info
[ROOT CAUSE ANALYSIS]
{rca_context}                                # <-- RAW topology data
[DECISION MEMORY]
{memory_str}                                 # <-- Past decisions with customer details
...
REVENUE AT RISK: ${predicted_revenue_loss}   # <-- Financial data
"""
```

**Nothing is scrubbed before this prompt is sent to Google.**

Similarly, the `llm_adapter.py` docstring says "*Adapters route through local PII scrubbing before egress*" ([line 6](file:///Users/himanshu/Projects/Pedkai/backend/app/services/llm_adapter.py#L6)) but the code shows **no scrubbing call anywhere** in either the adapter or the service.

**Action Required**:
1. Integrate `PIIScrubber.scrub()` into `llm_service.py` before prompt construction
2. Integrate `PIIScrubber.scrub()` into `llm_adapter.py` before the `generate()` call
3. Store the `scrub_manifest` alongside the prompt hash for audit trail

---

### 🔴 B-3: AUTHENTICATION IS A MOCK — NOT PRODUCTION-READY

**Severity**: 🔴 CRITICAL  
**Files**: [auth.py](file:///Users/himanshu/Projects/Pedkai/backend/app/api/auth.py)

The entire authentication system is a hardcoded dictionary with two users ([lines 19-30](file:///Users/himanshu/Projects/Pedkai/backend/app/api/auth.py#L19-L30)):

```python
MOCK_USERS_DB = {
    "admin": {"username": "admin", "role": Role.ADMIN, "tenant_id": "default"},
    "operator": {"username": "operator", "role": Role.OPERATOR, "tenant_id": "default"},
}
```

Password validation is a **plaintext string comparison** ([line 50](file:///Users/himanshu/Projects/Pedkai/backend/app/api/auth.py#L50)):
```python
if form_data.password != expected_password:
```

There is:
- No password hashing (no bcrypt, no argon2)
- No user database table
- No user registration or password change endpoint
- No refresh token mechanism (JWT expires in 30 minutes, then the user must re-login with plaintext credentials)
- No brute-force protection on the `/token` endpoint
- No token revocation (JWTs are valid until expiry — there is no blacklist)
- Only 2 users possible — `admin` and `operator`. The `shift_lead` and `engineer` roles defined in [security.py](file:///Users/himanshu/Projects/Pedkai/backend/app/core/security.py#L92-L98) are impossible to use because there are no users mapped to them
- Both users are in tenant `default` — multi-tenant auth is paper-only

**Action Required**:
1. Create a `users` database table with hashed passwords
2. Use `passlib[bcrypt]` or `argon2-cffi` for password hashing
3. Add rate limiting to the `/token` endpoint
4. Implement refresh tokens for session management
5. Create users for `shift_lead` and `engineer` roles
6. Support multiple `tenant_id` values in user records

---

### 🔴 B-4: SCORECARD USES FABRICATED COUNTERFACTUAL DATA

**Severity**: 🔴 CRITICAL — CFO's §2.2 concern materialised  
**Files**: [autonomous.py](file:///Users/himanshu/Projects/Pedkai/backend/app/api/autonomous.py#L70-L90)

The `GET /autonomous/scorecard` endpoint fabricates "non-Pedkai zone" metrics using **hardcoded magic numbers**:

```python
BASELINE_NON_PEDKAI_MTTR = 180.0             # Line 72 — completely made up
BASELINE_INCIDENT_RATIO = 2.4                 # Line 73 — completely made up
non_pedkai_zone_incident_count = int(pedkai_count * BASELINE_INCIDENT_RATIO)  # Line 79
revenue_protected = pedkai_count * 2500.0     # Line 84 — arbitrary £2,500 per incident
incidents_prevented = int(pedkai_count * 0.35)  # Line 85 — 35% pulled from thin air
uptime_gained_minutes = pedkai_count * 45.0    # Line 86 — arbitrary 45 min per incident
```

The CFO specifically warned about counterfactual metrics needing "an auditable methodology" (§2.2, item 4). This code is the opposite — it manufactures impressive-looking numbers that have zero basis in reality.

The `confidence_interval` is set to `"±10% (verified against DB baselines)"` ([line 88](file:///Users/himanshu/Projects/Pedkai/backend/app/api/autonomous.py#L88)) — this claim is fabricated. There are no DB baselines for the non-Pedkai zone.

Separately, the MTTR fallback of `45.0` minutes on [line 69](file:///Users/himanshu/Projects/Pedkai/backend/app/api/autonomous.py#L69) is used when there are 0 closed incidents:
```python
avg_mttr = (total_minutes / closed_count) if closed_count > 0 else 45.0  # Fallback to a realistic baseline
```
This is another fabricated number presented as data.

**Action Required**:
1. Remove all hardcoded baselines from the scorecard endpoint
2. If there is no real comparison data, return `null` with a message explaining that baseline data collection is in progress
3. Add a `methodology` field that links to an auditable methodology document and flag all counterfactual metrics as `"estimated"` vs `"measured"`
4. The `confidence_interval` must be computed, not hardcoded

---

### 🔴 B-5: DEEP-DIVE ENDPOINT HAS HARDCODED REASONING CHAIN

**Severity**: 🔴 HIGH  
**Files**: [service_impact.py:203-247](file:///Users/himanshu/Projects/Pedkai/backend/app/api/service_impact.py#L203-L247)

The `GET /service-impact/deep-dive/{cluster_id}` endpoint returns a **hardcoded reasoning chain** that is identical for every cluster regardless of the actual cluster data:

```python
"reasoning_chain": [
    {"step": 1, "description": f"Temporal clustering: grouped {total_alarms} related events...",
     "confidence": 0.94, "source": "autonomous_shield:temporal_engine"},
    {"step": 2, "description": "Topology check: all events localized to same backhaul hub via graph adjacency.",
     "confidence": 0.88, "source": "autonomous_shield:topology_graph"},
    {"step": 3, "description": "Business impact: identified potential SLA breach for premium segment.",
     "confidence": 0.91, "source": "autonomous_shield:cx_intelligence"},
],
"noise_reduction_pct": 82.5,   # <-- hardcoded 82.5% for ALL clusters
```

The confidence scores (0.94, 0.88, 0.91) are hardcoded. The `noise_reduction_pct` is always 82.5%. The step 2 and 3 descriptions are identical strings regardless of input. This is mock data dressed up as real analysis.

Additionally, the code references an undefined symbol on [line 215](file:///Users/himanshu/Projects/Pedkai/backend/app/api/service_impact.py#L215):
```python
result = await db.execute(select(DecisionTraceORM).limit(5))
```
But `DecisionTraceORM` is **never imported** in this file — this is a runtime `NameError` that would crash the endpoint.

**Action Required**:
1. Calculate reasoning chains dynamically from actual cluster data
2. Fix the import error (`DecisionTraceORM` not imported)
3. Compute noise reduction percentage from actual alarm counts, not hardcode 82.5%

---

## Part 2: HIGH-Priority Findings (Must Be Fixed Before Pilot)

---

### 🟡 H-1: FRONTEND DISPLAYS FABRICATED KPIs

**Files**: [page.tsx:328-329](file:///Users/himanshu/Projects/Pedkai/frontend/app/page.tsx#L328-L329)

The dashboard header displays hardcoded stats:
```tsx
<StatCard icon={<Clock />} label="MTTR" value="14m" />
<StatCard icon={<CheckCircle />} label="Uptime" value="99.98%" />
```

These are static strings. They are never fetched from the backend. An operator looking at this dashboard would believe MTTR is 14 minutes and uptime is 99.98% — regardless of reality. This is misleading.

**Action Required**: Wire these to real API endpoints (e.g., `/api/v1/autonomous/scorecard` for MTTR, `/api/v1/health` for uptime).

---

### 🟡 H-2: NO CONFIDENCE SCORING ON LLM OUTPUTS

**Files**: [llm_service.py](file:///Users/himanshu/Projects/Pedkai/backend/app/services/llm_service.py)

Our AI Director (§2.5) mandated confidence scoring on all AI-generated recommendations. The `generate_explanation()` method returns a plain string from Gemini with no confidence score, no grounding validation, and no fallback to templates.

There is **no mention of "confidence"** anywhere in `llm_service.py` (confirmed by grep). The LLM output is returned verbatim with only a policy section appended.

**Action Required**:
1. Add a confidence score to every LLM response based on: decision memory similarity, causal evidence strength, and grounding validation
2. If confidence is below a configurable threshold, fall back to a structured template instead of Gemini's free-text output
3. Return the confidence score in the incident response schema

---

### 🟡 H-3: NO "AI-GENERATED" WATERMARK ON LLM OUTPUTS

**Files**: All LLM-facing endpoints (incidents, service_impact, autonomous)

Our Legal Counsel (§2.14, item 4) mandated `"AI-generated"` watermarks on all LLM outputs in the UI. Neither the backend responses nor the frontend rendering include any such watermark. The SITREP panel in [page.tsx:404-408](file:///Users/himanshu/Projects/Pedkai/frontend/app/page.tsx#L404-L408) shows:
```tsx
<h3 className="text-cyan-400 text-xs font-black uppercase tracking-widest">Autonomous SITREP</h3>
<p>Critical anomaly detected on {selectedAlarm.alarmedObject?.id}. AI Analysis pending.</p>
```

There is no visual indicator that this content was generated by an AI system.

**Action Required**:
1. Add `"ai_generated": true` flag and `"ai_watermark": "This content was generated by Pedkai AI"` to all LLM-sourced API responses
2. Render a visible `[AI Generated]` badge in the frontend on all AI-produced content

---

### 🟡 H-4: NO WEBSOCKET OR SSE — POLLING ONLY

**Files**: [page.tsx:100](file:///Users/himanshu/Projects/Pedkai/frontend/app/page.tsx#L100)

Our CTO (§2.3) mandated WebSocket or SSE for real-time push. The frontend uses **REST polling** at 10-second intervals:
```tsx
const interval = setInterval(fetchAlarms, 10000) // Polling
```

Grep confirms: zero references to `websocket`, `WebSocket`, `SSE`, or `EventSource` anywhere in the codebase. This means:
- Alarm updates are delayed by up to 10 seconds
- Each connected client generates 6 requests/minute regardless of changes (wasteful)
- The demo's real-time alarm animations (fault propagation, alarm wall) are impossible with this architecture

**Action Required**: Implement WebSocket or SSE endpoint for real-time alarm and incident push notifications.

---

### 🟡 H-5: TENANT ISOLATION BYPASS IN AUDIT TRAIL

**Files**: [incidents.py:263](file:///Users/himanshu/Projects/Pedkai/backend/app/api/incidents.py#L263)

The `get_audit_trail()` endpoint calls `_get_or_404(db, incident_id)` **without passing `tenant_id`**:
```python
incident = await _get_or_404(db, incident_id)  # No tenant_id!
```

Compare with all other endpoints that correctly pass `current_user.tenant_id`:
```python
incident = await _get_or_404(db, incident_id, current_user.tenant_id)  # Correct
```

This means any authenticated user from any tenant can read the audit trail of any incident from any other tenant. This is a **cross-tenant data leak** in the most sensitive part of the system (the regulatory audit trail).

**Action Required**: Pass `current_user.tenant_id` to `_get_or_404()` in the `get_audit_trail()` endpoint.

---

### 🟡 H-6: RATE LIMITER IS IN-MEMORY AND PER-PROCESS

**Files**: [topology.py:32-54](file:///Users/himanshu/Projects/Pedkai/backend/app/api/topology.py#L32-L54)

The topology rate limiter uses a Python dict:
```python
_rate_limit_store: dict = {}
```

This means:
- Rate limits reset on every server restart
- In multi-worker deployments (Gunicorn, Kubernetes), each worker has its own counter — an attacker can bypass the 10 req/min limit by hitting different workers
- No rate limiting exists on any other endpoint (incidents, service-impact, autonomous)

**Action Required**:
1. Use Redis-backed rate limiting for production (e.g., `slowapi` with Redis backend)
2. Apply rate limiting to all sensitive endpoints, not just topology

---

### 🟡 H-7: `llm_service.py` HAS DUPLICATE AND DEAD CODE

**Files**: [llm_service.py:113-118](file:///Users/himanshu/Projects/Pedkai/backend/app/services/llm_service.py#L113-L118) and [line 142](file:///Users/himanshu/Projects/Pedkai/backend/app/services/llm_service.py#L142)

The sampling logic has dead code from an incomplete refactor:
```python
if random.random() > self.sampling_rate:
    pass  # Line 114-115 — does nothing
else:
    pass  # Line 117-118 — does nothing

# ...then later on line 142:
should_bypass_sampling = False  # Duplicate of line 121
```

The variable `should_bypass_sampling` is assigned on line 121, then re-assigned to the same value on line 142. The `random.random()` check on line 113 results in two `pass` statements that do nothing. This is evidence of an incomplete refactor — the code works but is confusing and error-prone.

**Action Required**: Clean up the dead code path.

---

### 🟡 H-8: CLUSTERS ENDPOINT QUERIES `decision_traces` TABLE, NOT ALARMS

**Files**: [service_impact.py:101-108](file:///Users/himanshu/Projects/Pedkai/backend/app/api/service_impact.py#L101-L108)

The alarm cluster endpoint queries:
```sql
SELECT id, title, severity, status, entity_id, created_at
FROM decision_traces
```

Decision traces are **not alarms**. They are decision records from the decision memory system. This means the alarm correlation service is clustering decisions, not alarms — which produces meaningless correlation results. The OSS Lead (§2.9) specifically said Pedkai should consume pre-correlated alarms from the OSS feed, not reprocess its own internal decisions.

**Action Required**: Query actual alarm data (TMF642 alarms from the database), not decision traces.

---

### 🟡 H-9: SERVICE IMPACT ENDPOINT HAS NO TENANT ISOLATION

**Files**: [service_impact.py:92-162](file:///Users/himanshu/Projects/Pedkai/backend/app/api/service_impact.py#L92-L162)

The `GET /service-impact/clusters` and `GET /service-impact/noise-wall` and `GET /service-impact/deep-dive/{cluster_id}` endpoints have **no tenant filtering**. They query `decision_traces` without a `WHERE tenant_id = :tid` clause. Any authenticated user from any tenant sees all data.

Compare with the topology endpoints that correctly enforce `WHERE tenant_id = :tid` everywhere.

**Action Required**: Add mandatory `tenant_id` filtering to all service-impact endpoints.

---

### 🟡 H-10: PROACTIVE COMMS DEFAULTS TO OPT-IN

**Files**: [proactive_comms.py:69](file:///Users/himanshu/Projects/Pedkai/backend/app/services/proactive_comms.py#L69)

```python
return getattr(customer, "consent_proactive_comms", True)  # Default True = opt-in
```

If the `consent_proactive_comms` field does not exist on the customer record (which it won't, because it's accessed via `getattr` with a default), the system **defaults to opt-in**. Our Customer Service Director (§2.11) and Legal Counsel (§2.14) both required explicit consent. The GDPR lawful basis for proactive communications requires **opt-in**, not opt-out.

Note: The error path on line 72 correctly defaults to `False`, but the happy path on line 69 defaults to `True`, creating an inconsistency.

**Action Required**: Default to `False` (require explicit opt-in). Add a `consent_proactive_comms` column to the `CustomerORM` model.

---

## Part 3: MEDIUM-Priority Findings (Should Be Fixed Before Production)

---

### 🟢 M-1: FRONTEND IS A SINGLE-PAGE MONOLITH

**Files**: [page.tsx](file:///Users/himanshu/Projects/Pedkai/frontend/app/page.tsx) — 564 lines in one file

The CTO (§2.3) warned about "frontend monolith risk." The entire Next.js frontend is a single 564-line file containing:
- Login screen
- Dashboard layout
- Alarm ingress feed
- Capacity planning view
- Stat cards, alarm cards (all inline components)
- All state management (`useState` — no shared data layer, no React Query, no SWR)

Three of the five sidebar icons (`topology`, `telelogs`, `processing`) show a toast saying "coming in a future release" (line 179). These views do not exist.

**Findings**:
- No state management library (just scattered `useState`)
- No component separation (everything in one file)
- No tests for the frontend
- API token stored in `useState` — lost on page refresh (no persistence)
- No error boundary
- No loading states for most API calls

---

### 🟢 M-2: lLM SERVICE USES DUAL PROVIDER PATTERNS

**Files**:  
- [llm_service.py](file:///Users/himanshu/Projects/Pedkai/backend/app/services/llm_service.py) — defines its own `LLMProvider` ABC and `GeminiProvider`  
- [llm_adapter.py](file:///Users/himanshu/Projects/Pedkai/backend/app/services/llm_adapter.py) — defines a separate `LLMAdapter` ABC and `GeminiAdapter`

There are **two parallel abstraction layers** for LLM integration that do the same thing differently:
1. `LLMProvider` (used by `llm_service.py`) — async, simple, no prompt hashing
2. `LLMAdapter` (never actually called by anything) — sync in `GeminiAdapter`, has prompt hashing and model version tracking

The `llm_adapter.py` was built to address our AI Director's model versioning concern (§2.5) but is **dead code** — nothing imports or uses it except comments.

**Action Required**: Choose one abstraction layer. Wire `llm_service.py` to use `llm_adapter.py` (which has the better design: prompt hashing, model versioning, PII scrubbing integration point).

---

### 🟢 M-3: NO API VERSIONING STRATEGY

**Files**: [main.py](file:///Users/himanshu/Projects/Pedkai/backend/app/main.py)

The CTO (§2.3) asked for an API versioning strategy. Currently:
- Internal APIs use `/api/v1/` prefix
- TMF APIs use `/tmf-api/*/v4` versioned paths

There is no plan, mechanism, or infrastructure for introducing `/api/v2/` when these APIs evolve. No versioning middleware, no deprecation headers, no content negotiation.

---

### 🟢 M-4: `GeminiAdapter` USES SYNC API, `GeminiProvider` USES ASYNC

**Files**:  
- [llm_adapter.py:67](file:///Users/himanshu/Projects/Pedkai/backend/app/services/llm_adapter.py#L67) — `client.models.generate_content()` **(sync)**
- [llm_service.py:39](file:///Users/himanshu/Projects/Pedkai/backend/app/services/llm_service.py#L39) — `client.aio.models.generate_content()` **(async)**

If someone switches to using `llm_adapter.py`, the `GeminiAdapter.generate()` method blocks the event loop because it uses the synchronous Gemini client. This would freeze the entire FastAPI server during LLM calls.

**Action Required**: Change `GeminiAdapter` to use `client.aio.models.generate_content()`.

---

### 🟢 M-5: TOPOLOGY STALENESS METRIC IS MISLEADING

**Files**: [topology.py:250-253](file:///Users/himanshu/Projects/Pedkai/backend/app/api/topology.py#L250-L253)

The staleness logic considers topology **relationships** older than 24 hours as "stale":
```python
stale_res = await db.execute(
    text("SELECT COUNT(*) FROM topology_relationships WHERE tenant_id = :tid AND created_at < :yesterday"),
    ...
)
```

Network topology relationships (e.g., "Cell-A connects to Backhaul-B") don't change hourly. A relationship created 48 hours ago that is still valid would be flagged as "stale." The staleness metric should be based on when the topology was last **synchronized**, not when individual records were created.

---

### 🟢 M-6: EMERGENCY SERVICE DETECTION IS FRAGILE

**Files**: [incidents.py:79-83](file:///Users/himanshu/Projects/Pedkai/backend/app/api/incidents.py#L79-L83)

Emergency service detection relies on string matching:
```python
if "EMERGENCY" in entity_external_id.upper() ...
```

An entity with external_id `"EMERGENCY_EXIT_SIGN_CELL_42"` would trigger unconditional P1 classification. This is too broad. An entity with external_id `"999-dialout-primary"` (the actual emergency services gateway) would NOT be detected.

**Action Required**: Use the topology graph's entity_type field (`EMERGENCY_SERVICE`) for detection, not string matching on external_id.

---

### 🟢 M-7: BSS REVENUE QUERY HAS N+1 PROBLEM

**Files**: [bss_adapter.py:77-98](file:///Users/himanshu/Projects/Pedkai/backend/app/services/bss_adapter.py#L77-L98)

The `get_revenue_at_risk()` method calls `get_account_by_customer_id()` **in a loop** for every customer:
```python
for cid in customer_ids:
    account = await self._service.get_account_by_customer_id(cid)
```

With 50 impacted customers, this is 50 individual database queries. At 200K alarms/day (the OSS Lead's load target), this will be a performance bottleneck.

**Action Required**: Batch the query with `WHERE customer_id IN :ids`.

---

### 🟢 M-8: CX INTELLIGENCE USES RECURSIVE CTE WITHOUT DEPTH LIMIT

**Files**: [cx_intelligence.py:64-74](file:///Users/himanshu/Projects/Pedkai/backend/app/services/cx_intelligence.py#L64-L74)

The recursive CTE for downstream impact traversal has no depth limit:
```sql
WITH RECURSIVE downstream_impact AS (
    SELECT to_entity_id FROM topology_relationships WHERE from_entity_id = :site_id
    UNION
    SELECT tr.to_entity_id FROM topology_relationships tr
    INNER JOIN downstream_impact di ON tr.from_entity_id = di.to_entity_id
)
```

In a large graph with cycles (which are possible without acyclicity enforcement), this query will run indefinitely or exhaust memory. The topology router correctly limits to `max_hops=5` but the CX intelligence service does not.

**Action Required**: Add `LIMIT 1000` or a depth counter to the recursive CTE.

---

## Part 4: Status of Committee's 26 Mandatory Amendments

| # | Amendment | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Remove `execute_preventive_action()` | ✅ **Done** | Method removed from `autonomous_shield.py`. Docstring confirms design principle. |
| 2 | 3 human gates in incident lifecycle | ✅ **Done** | `approve-sitrep`, `approve-action`, `close` endpoints with correct RBAC scopes. |
| 3 | LLM data classification + VPC controls | ❌ **NOT DONE** | PII scrubber exists but is dead code (B-2). No VPC/Vertex AI integration. |
| 4 | DPIA and regulatory framework | ❌ **NOT DONE** | No evidence of a DPIA document, data classification registry, or regulatory mapping. |
| 5 | NOC operational runbook | ❌ **NOT DONE** | No runbook, no degraded-mode procedures, no escalation matrix found in codebase. |
| 6 | Emergency service unconditional P1 | ⚠️ **Partial** | Policy engine hardcodes P1 for `EMERGENCY_SERVICE` type. Incident creation relies on fragile string matching (M-6). |
| 7 | Audit trail (approver + model version + timestamps) | ⚠️ **Partial** | Audit trail endpoint exists but has tenant isolation bug (H-5). `llm_model_version` and `llm_prompt_hash` columns exist in `IncidentORM` but are never populated. |
| 8 | LLM grounding validation + confidence scoring | ❌ **NOT DONE** | No confidence scoring, no grounding validation, no template fallback (H-2). |
| 9 | Topology accuracy monitoring + refresh strategy | ⚠️ **Partial** | Health endpoint exists with staleness metric, but logic is misleading (M-5). No topology refresh strategy. |
| 10 | BSS adapter abstraction layer | ✅ **Done** | `bss_adapter.py` with `LocalBSSAdapter` and abstract `BSSAdapter` class. |
| 11 | ARPU fallback → "unpriced" flag | ✅ **Done** | `RevenueResult` model uses `unpriced_customer_count` and `requires_manual_valuation`. |
| 12 | Multi-tenant isolation testing | ⚠️ **Partial** | Test file exists (`test_multi_tenant_isolation.py`, `test_ruthless_isolation.py`) but audit trail and service-impact endpoints leak cross-tenant data (H-5, H-9). |
| 13 | WebSocket/SSE for real-time push | ❌ **NOT DONE** | REST polling only (H-4). |
| 14 | Load test at 200K alarms/day | ⚠️ **Partial** | A Locust file exists (`tests/load/locustfile.py`) but no evidence of a 200K alarm test run or results. |
| 15 | AI maturity ladder | ❌ **NOT DONE** | No ladder definition, no progression criteria. |
| 16 | TMF mapping for new APIs (621, 656, 921) | ❌ **NOT DONE** | No TMF621, TMF656, or TMF921 implementation or mapping. |
| 17 | Shadow-mode pilot architecture | ❌ **NOT DONE** | No shadow-mode capability. |
| 18 | NOC training curriculum | ❌ **NOT DONE** | No training materials. |
| 19 | Demo milestones per work stream | ❌ **NOT DONE** | No milestone definitions. |
| 20 | Per-incident LLM cost model | ❌ **NOT DONE** | No cost tracking. Sampling rate exists but cost is not measured. |
| 21 | Customer prioritisation algorithm (configurable) | ❌ **NOT DONE** | Fixed revenue-based ordering only. |
| 22 | RBAC granularity for new endpoints | ⚠️ **Partial** | Scopes defined in `security.py` but only 2 users exist (B-3). `shift_lead` and `engineer` roles are unreachable. |
| 23 | Bias drift detection in RLHF loop | ❌ **NOT DONE** | No bias detection in `rl_evaluator.py`. |
| 24 | Drift detection calibration protocol | ❌ **NOT DONE** | Fixed 15% threshold in `autonomous_shield.py` (not configurable). No false-positive rate tracking. |
| 25 | Dashboard progressive disclosure design | ❌ **NOT DONE** | Dashboard shows all data at once. Progressive disclosure not implemented. |
| 26 | Data retention policies | ❌ **NOT DONE** | No TTL, no archival, no cleanup jobs. |

**Summary**: Of 26 mandatory amendments, **4 are done, 6 are partially done, and 16 are not started.**

---

## Part 5: New Regressions Introduced by the Vendor

These are issues that did not exist before the vendor's work, or were caused by incomplete remediation:

1. **Dead code from incomplete refactoring** — `llm_service.py` has two orphaned sampling code paths (H-7)
2. **Dual LLM provider abstractions** — Two competing patterns (`LLMProvider` vs `LLMAdapter`) that are inconsistent (M-2)
3. **`GeminiAdapter` blocks the event loop** — Sync API call in an async method (M-4)
4. **`DecisionTraceORM` import missing** in `service_impact.py` — Would crash at runtime (B-5)
5. **Audit trail tenant bypass** — Other incident endpoints correctly enforce tenant isolation but `get_audit_trail()` was missed (H-5)

---

## Part 6: What the Vendor Did Well

In the spirit of constructive feedback, the committee acknowledges these areas of solid work:

1. **Human gates are properly enforced** — The incident lifecycle correctly prevents stage-skipping and requires specific RBAC scopes
2. **Policy engine is well-designed** — YAML-based, uses `simpleeval` (not `eval()`), supports integrity verification with checksums
3. **BSS adapter abstraction** is clean — `RevenueResult` model with `unpriced` flag instead of ARPU fallback is correct
4. **Autonomous shield correctly does NOT execute actions** — No `execute_preventive_action()` method exists
5. **Proactive comms correctly drafts but never sends** — The `draft_pending_review` pattern is right
6. **Alarm correlation service** — Clean separation between OSS pre-correlation and Pedkai business enrichment
7. **PII scrubber code quality** — The implementation itself is thorough (7 regex patterns, SHA-256 audit manifest). Just needs to be actually wired in.
8. **RBAC scope granularity** — The 17 defined scopes are well-thought-out and align with the committee's requirements

---

## Part 7: Corrective Action Priorities

The committee requires the following actions in order of priority:

### Immediate (within 48 hours)
1. **Rotate all API keys and credentials** (B-1)
2. **Remove `.env` from git tracking** (B-1)
3. **Wire PII scrubber into LLM pipeline** (B-2)
4. **Fix audit trail tenant isolation** (H-5)
5. **Fix service-impact tenant isolation** (H-9)
6. **Fix `DecisionTraceORM` import** (B-5)

### Short-term (within 1 week)
7. Replace mock user database with real auth (B-3)
8. Remove fabricated scorecard baselines (B-4)
9. Fix deep-dive hardcoded reasoning chain (B-5)
10. Add AI-generated watermarks (H-3)
11. Fix emergency service detection logic (M-6)

### Medium-term (within 2 weeks)
12. Implement WebSocket/SSE (H-4)
13. Add LLM confidence scoring (H-2)
14. Wire frontend KPIs to real APIs (H-1)
15. Consolidate LLM adapters (M-2)
16. Add Redis-backed rate limiting (H-6)

### Before pilot
17. Complete remaining 16 unstarted mandatory amendments
18. Full penetration test (OWASP API Top 10)
19. Load test at 200K alarms/day with results documented

---

*Prepared by the Executive Committee — 18 February 2026*  
*Next review: Upon completion of Immediate corrective actions*
