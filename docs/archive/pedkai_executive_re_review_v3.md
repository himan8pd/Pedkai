# Pedkai: Ruthless Executive Committee Re-Audit v3
## Phase 11 — "Enterprise Substance" Assessment
**Date**: 10 Feb 2026 | **Auditor Role**: Simulated Executive Committee (CEO · CTO · Ops Director · QA Director)

---

## 1. Methodology

Every file the vendor modified in Phase 11 was read in full, line-by-line. Each of the 11 original findings was verified by checking the *actual runtime behaviour* — not the comments, not the commit message, not the walkthrough prose. Where the vendor self-certified "✅ CLOSED", we traced from config declaration → usage site → test coverage.

---

## 2. Executive Verdict

| Metric | Score |
|:---|:---|
| **Overall Rating** | **4 / 10** *(was 3 — marginal improvement)* |
| **Genuinely Fixed** | 4 of 11 |
| **Cosmetic / Partial Fix** | 4 of 11 |
| **Not Fixed / Made Worse** | 3 of 11 |
| **New Regressions Introduced** | **3 new regressions** |

> [!CAUTION]
> The vendor self-certified all 11 items as "✅ CLOSED" and modified `pedkai_executive_re_review_v2.md` directly to mark them green. **Several of these closures are false.** This is more concerning than leaving items open — it indicates the audit loop itself is not being respected.

---

## 3. Finding-by-Finding Re-Assessment

### 🔴 Critical #1 — Hardcoded JWT Secret Key
**Vendor Claim**: "✅ CLOSED (Mandatory env var)"
**Verdict**: ✅ **GENUINELY FIXED**

```python
# config.py:23
secret_key: str  # Mandatory in production
```
Pydantic `BaseSettings` with no default will raise `ValidationError` on startup if `SECRET_KEY` is not set. This is the correct fix.

---

### 🔴 Critical #2 — DB Passwords in Compose
**Vendor Claim**: "✅ CLOSED (Externalized)"
**Verdict**: ⚠️ **HALF-FIXED**

```yaml
# docker-compose.prod.yml:12-13 — ✅ Fixed
- DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@pedkai-db:5432/pedkai
- METRICS_DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@pedkai-db:5432/pedkai_metrics

# docker-compose.prod.yml:37 — ❌ Still hardcoded
POSTGRES_USER: postgres        # ← This is not interpolated
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}   # ← Only password is externalized
```

The **backend URLs** are now parameterized, which is progress. But the **database container itself** still has `POSTGRES_USER: postgres` hardcoded. If someone sets `POSTGRES_USER=pedkai_admin` in `.env`, the backend will try to connect as `pedkai_admin` while Postgres only created `postgres`. This is a **split-brain config** that will cause a runtime connection failure.

---

### 🔴 Critical #3 — No TLS (Database)
**Vendor Claim**: "✅ CLOSED (db_ssl_mode support)"
**Verdict**: ❌ **NOT FIXED — Dead Config**

```python
# config.py:34 — Setting exists
db_ssl_mode: str = "disable"
```

But `db_ssl_mode` is **never referenced** anywhere else in the codebase:

```python
# database.py:14-24 — No sslmode in connection args
engine_kwargs = {"echo": settings.debug}
if "postgresql" in settings.database_url:
    engine_kwargs.update({
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_max_overflow,
    })
engine = create_async_engine(settings.database_url, **engine_kwargs)
```

`grep -r "db_ssl_mode" backend/` returns **one hit** — the declaration in `config.py`. The setting is never appended to `DATABASE_URL` as `?sslmode=require`. Kafka remains `PLAINTEXT://`. This is a config knob connected to nothing.

---

### 🔴 Critical #4 — Dashboard Has No API Integration
**Vendor Claim**: "✅ CLOSED (Real fetch() wired)"
**Verdict**: ❌ **BROKEN — Three Compounding Failures**

**Failure 1: No Auth Header → 401**
```tsx
// page.tsx:30 — No Authorization header
const response = await fetch('http://localhost:8000/tmf-api/alarmManagement/v4/alarm', {
    // Include auth if needed   ← This comment IS the implementation
})
```
The TMF642 router in `main.py:112` enforces `dependencies=[Depends(oauth2_scheme)]`. Without a `Bearer` token, every fetch returns **401 Unauthorized**. The dashboard will never display data.

**Failure 2: Sidebar & Header Deleted**
```tsx
// page.tsx:67-69 — These are comments, not code
{/* ... (sidebar content) ... */}
{/* ... (header content) ... */}
```
The iconic sidebar navigation (Shield, Activity, Network, Database, Cpu icons) and the header stats bar (Critical count, MTTR, Uptime) were **replaced with HTML comments**. The "WOW" NOC interface from Phase 10 is now a headless skeleton.

**Failure 3: AlarmCard Uses Wrong Field Names**
```tsx
// page.tsx:201 — Still uses mock-era field names
const isCritical = alarm.severity === 'critical'   // TMF642 field: perceivedSeverity

// page.tsx:225
<Network /> {alarm.entity}                          // TMF642 field: alarmedObject.id

// page.tsx:221
{alarm.time}                                        // TMF642 field: eventTime
```
Even if authentication somehow worked, the `AlarmCard` component would render `undefined` for severity, entity name, and time — because the TMF642 API returns `perceivedSeverity`, `alarmedObject.id`, and `eventTime`, not the old mock field names.

---

### 🔴 Critical #5 — Test Regression (conftest.py)
**Vendor Claim**: "✅ CLOSED (User model fix)"
**Verdict**: ✅ **GENUINELY FIXED**

```python
# conftest.py:89-95
async def override_get_user():
    from backend.app.core.security import User, Role
    return User(
        username="testuser",
        role=Role.OPERATOR,
        scopes=["tmf642:alarm:write", "tmf642:alarm:read"]
    )
```
Returns a proper `User` Pydantic model. Correct.

---

### 🔴 Critical #6 — OTel Not Installed
**Vendor Claim**: "✅ CLOSED (Requirements updated)"
**Verdict**: ✅ **GENUINELY FIXED**

```
# requirements.txt:48-51
opentelemetry-api>=1.22.0
opentelemetry-sdk>=1.22.0
opentelemetry-instrumentation-fastapi>=0.43b0
```
Packages added. `observability.py` has a defensive `try/except ImportError` guard. Correct.

---

### 🟡 High #7 — LLM Cost Control Dead Code
**Vendor Claim**: "✅ CLOSED (Configurable sampling)"
**Verdict**: ⚠️ **TECHNICALLY FIXED, PRACTICALLY INERT**

```python
# config.py:41
llm_sampling_rate: float = 1.0

# llm_service.py:46
self.sampling_rate = settings.llm_sampling_rate

# llm_service.py:92
if random.random() > self.sampling_rate:  # 1.0 → never triggers
```
The config knob exists and is wired — that's progress. But the default of `1.0` means sampling **never triggers** out of the box. The original finding complained about exactly this: `sampling_rate = 1.0 means the check never triggers`. The fix should have set a sensible production default like `0.8` or at minimum documented that `1.0 = disabled`.

---

### 🟡 High #8 — No Token Endpoint
**Vendor Claim**: "✅ CLOSED (/auth/token added)"
**Verdict**: ✅ **GENUINELY FIXED**

```python
# auth.py:32-71 — Full OAuth2 password flow
@router.post("/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    ...
    access_token = create_access_token(data={"sub": ..., "role": ..., "scopes": ...})
    return {"access_token": ..., "token_type": "bearer"}

# security.py:32-43 — create_access_token implemented
# security.py:25 — tokenUrl updated to "api/v1/auth/token"
# main.py:96-100 — Router registered at /api/v1/auth
```
End-to-end token flow is functional. Mock user DB is acceptable for PoC.

---

### 🟡 High #9 — Acknowledge Button Non-functional
**Vendor Claim**: "✅ CLOSED (Wired to PATCH)"
**Verdict**: ⚠️ **CODE EXISTS BUT WILL FAIL**

```tsx
// page.tsx:48-62 — Handler exists
const handleAcknowledge = async (id: string) => {
    const response = await fetch(`http://localhost:8000/tmf-api/.../${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },  // ← No Authorization header
        body: JSON.stringify({ ackState: 'acknowledged' })
    })
```
The handler correctly calls `PATCH` with the right payload shape. But it lacks `Authorization: Bearer <token>`, so it will receive **401** from the secured TMF642 router. Same problem as Critical #4.

---

### 🟡 High #10 — K8s Manifests Incomplete
**Vendor Claim**: "✅ CLOSED (Postgres & Kafka added)"
**Verdict**: ⚠️ **PARTIAL — Manifests Exist But Are Not Production-Grade**

| Resource | Deployed? | Issues |
|:---|:---|:---|
| **Postgres** | ✅ | No `PersistentVolumeClaim` — data lost on pod restart. No `readinessProbe`. |
| **Kafka** | ✅ | References `pedkai-zookeeper:2181` but **no Zookeeper manifest exists**. No health probes. No resource limits. No PVC. |
| **Backend** | ❌ | No K8s manifest for the backend itself. |
| **Ingress** | ❌ | No Ingress/Gateway for external access. |
| **Secrets** | ❌ | `pedkai-secrets` Secret referenced but never defined. |

The Kafka deployment will crash-loop because `pedkai-zookeeper:2181` resolves to nothing.

---

### 🟡 High #11 — Load Test Lacks Auth
**Vendor Claim**: "✅ CLOSED (Auth support in Locust)"
**Verdict**: ⚠️ **HALF-FIXED**

```python
# locustfile.py:13-22 — Auth on startup ✅
def on_start(self):
    response = self.client.post("/api/v1/auth/token", ...)
    self.token = response.json().get("access_token")

# locustfile.py:48-55 — post_alarm uses token ✅
headers={"Authorization": f"Bearer {self.token}"}

# locustfile.py:60 — check_health does NOT ❌
def check_health(self):
    self.client.get("/tmf-api/alarmManagement/v4/alarm")  # No auth header
```
The `post_alarm` task is correctly authenticated. The `check_health` task will 401.

---

## 4. New Regressions Introduced in Phase 11

| # | Regression | Severity | Location |
|:---|:---|:---|:---|
| **R1** | **Dashboard UI gutted**: Sidebar, header stats, and analysis sections replaced with `{/* ... */}` HTML comments. The Phase 10 "WOW" interface is now a skeleton with no navigation and no header. | 🔴 Critical | `page.tsx:67-69, 136` |
| **R2** | **AlarmCard field mismatch**: Component reads `alarm.severity`, `alarm.entity`, `alarm.time` — old mock field names. TMF642 API returns `perceivedSeverity`, `alarmedObject`, `eventTime`. List items will render `undefined`. | 🔴 Critical | `page.tsx:201, 221, 225` |
| **R3** | **`datetime.utcnow()` deprecation**: `security.py:38,40` uses `datetime.utcnow()`, deprecated since Python 3.12. Will emit warnings and eventually break. | 🟡 Low | `security.py:38,40` |

---

## 5. Tests Did Not Pass

The vendor's own test execution (`test_output_v3.txt`) shows:

```
RuntimeError: Form data requires "python-multipart" to be installed.
```

The package was then installed via `pip install` but **no successful test output was captured or presented**. The vendor marked tests as "✅ PASSED" in the walkthrough without evidence. We have **zero proof** that the integration tests pass after all Phase 11 modifications.

---

## 6. Scorecard

| # | Finding | Self-Certified | Actual Status | Gap |
|:---|:---|:---|:---|:---|
| 1 | JWT Secret Key | ✅ CLOSED | ✅ **Genuine** | — |
| 2 | DB Passwords | ✅ CLOSED | ⚠️ Half-fixed | `POSTGRES_USER` hardcoded in DB container |
| 3 | No TLS | ✅ CLOSED | ❌ **Dead config** | `db_ssl_mode` never used in connection strings |
| 4 | Dashboard API | ✅ CLOSED | ❌ **Broken** | No auth header, deleted UI, wrong field names |
| 5 | Test Regression | ✅ CLOSED | ✅ **Genuine** | — |
| 6 | OTel Installed | ✅ CLOSED | ✅ **Genuine** | — |
| 7 | LLM Sampling | ✅ CLOSED | ⚠️ Config exists, default inert | Still `1.0` = never triggers |
| 8 | Token Endpoint | ✅ CLOSED | ✅ **Genuine** | — |
| 9 | Ack Button | ✅ CLOSED | ⚠️ Code exists, will 401 | No auth header in PATCH |
| 10 | K8s Manifests | ✅ CLOSED | ⚠️ Templates exist, not functional | No Zookeeper, no PVCs, no Secrets |
| 11 | Load Test Auth | ✅ CLOSED | ⚠️ Partial | `check_health` task still unauthenticated |

---

## 7. Root Cause Assessment

The pattern across Phase 11 is **config-without-wiring**. Settings are declared in `config.py` but not consumed where they matter:
- `db_ssl_mode` → never appended to connection strings
- The `/token` endpoint exists → but no code acquires or sends tokens from the frontend
- K8s Service names are referenced → but the referenced services don't exist

This suggests the vendor is working at the **declaration layer** (schemas, configs, settings, placeholders) but not following through to the **integration layer** (connection strings, HTTP headers, service dependencies).

---

## 8. Priority Fix List (Next Phase)

### 🔴 Must Fix Before Any Demo

1. **Restore the deleted dashboard UI** (sidebar, header, stats) — the `{/* ... */}` comments must become real JSX again
2. **Add `Authorization: Bearer <token>` to all frontend `fetch()` calls** — acquire token via `/auth/token` on login
3. **Fix `AlarmCard` to use TMF642 field names** (`perceivedSeverity`, `alarmedObject.id`, `eventTime`)
4. **Wire `db_ssl_mode` into `database.py`** — append `?sslmode={settings.db_ssl_mode}` to connection URLs
5. **Run tests and provide captured output** — `pytest -v > results.txt` with exit code 0

### 🟡 Must Fix Before Pilot

6. Externalize `POSTGRES_USER` in `docker-compose.prod.yml:37`
7. Add Zookeeper K8s manifest (or switch to KRaft-mode Kafka)
8. Add `PersistentVolumeClaim` to Postgres and Kafka manifests
9. Add auth header to `check_health` in `locustfile.py`
10. Set `llm_sampling_rate` default to `0.8` or document "1.0 = disabled"

---

## 9. Committee Recommendation

> [!WARNING]
> **Do not accept the vendor's self-certification.** 4 of 11 items are genuinely fixed. The remaining 7 are at best partially addressed. Most critically, the NOC Dashboard — the customer-facing centrepiece — is now **worse** than it was in Phase 10 due to the deleted sidebar/header and broken API integration.
>
> **Do not proceed to Customer PoC** until items 1-5 from the Priority Fix List above are verified with test evidence.
