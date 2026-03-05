# Executive Committee Re-Audit: Pedkai (Post Phase 10 "Executive Rework")

**Date:** 2026-02-10
**Target:** Pedkai v0.1.0 (Post "Hardening v2")
**Scope:** Verify whether the vendor's Phase 10 rework genuinely closes the 14 open items from our previous Re-Review, or whether it introduces new risks.

> [!CAUTION]
> This audit is conducted by the same committee that authored the original feedback. We are checking the vendor's actual code, not their walkthrough claims.

---

## 1. Operations Director Re-Audit

**Previous Verdict:** 🟡 CONDITIONAL

| Original Gap | Vendor Claim | Evidence (Line-by-Line) | Verdict |
|:---|:---|:---|:---|
| **No Human-in-the-Loop UI** | ✅ "Built Next.js NOC Dashboard" | A `frontend/` directory now exists with a Next.js app. **However, the entire dashboard runs on hardcoded mock data** (`MOCK_ALARMS` at `page.tsx:20-48`). There is **zero `fetch()` or API integration** — no call to `GET /tmf-api/alarmManagement/v4/alarm`. It cannot display real alarms. | 🟡 |
| **RBAC (L1/L2/L3)** | ✅ "Implemented Admin/Operator/Viewer" | `security.py` now defines `Role.ADMIN`, `Role.OPERATOR`, `Role.VIEWER` with hierarchical scopes and real `jwt.decode()`. This is a genuine improvement. **However**, there is no `/token` endpoint to actually issue JWTs. No user registration or login flow exists. You cannot obtain a valid token without writing one manually using `python-jose`. | 🟡 |
| **"Acknowledge" Button** | ✅ (implied by dashboard) | The dashboard has a styled `<button>Acknowledge Alarm</button>` at `page.tsx:131-133`. **It has zero `onClick` handler.** It does nothing. It doesn't call `PATCH /alarm/{id}` to set `ackState`. It's cosmetic. | 🔴 |

### ⚠️ NEW FINDING: Test Regression

`conftest.py:89-90` still returns a **plain dict** `{"username": "testuser", "scopes": [...]}` for the `get_current_user` mock. But `security.py` now returns a **`User` Pydantic model** with a mandatory `role` field. Any test code that accesses `current_user.role` will crash with an `AttributeError`. **The existing tests have not been updated to match the new RBAC model.**

### Ops Director Verdict: 🟡 CONDITIONAL (Unchanged)

> The dashboard is a start and the UI design is visually impressive, but it's a **Potemkin village** — pure decoration with no backend wiring. My L1 engineers still cannot see real alarms or acknowledge them. The RBAC roles are defined but there's no way to actually log in and get a token. I cannot upgrade my rating until the dashboard fetches real data and the Acknowledge button works.

---

## 2. Global CEO Re-Audit

**Previous Verdict:** 🟡 PROVISIONAL

| Original Gap | Vendor Claim | Evidence | Verdict |
|:---|:---|:---|:---|
| **LLM Cost Control** | ✅ "Sampling-based cost control" | `llm_service.py:47` sets `self.sampling_rate = 1.0` (100%). At this value, the `random.random() > 1.0` check at line 93 is **mathematically impossible to trigger**. The cost control is **dead code**. There is no config setting to change this value, no token counter, and no budget tracker. | 🔴 |
| **LLM Vendor Lock-in** | ✅ "Provider abstraction layer" | `llm_service.py:21-35` introduces `LLMProvider` ABC and `GeminiProvider`. This is a **genuine architectural improvement**. Adding an `OllamaProvider` would be straightforward. **However**, `import google.generativeai as genai` is still at module top-level (line 8), meaning the package is required even if you never use Gemini. | 🟢 |
| **Single Point of Failure / K8s** | ✅ "K8s manifests provided" | `k8s/deployment.yaml` defines a 3-replica Deployment with health probes, resource limits, and a K8s Service. Database URL is loaded from a `Secret`. This is **solid and production-usable**. Missing: Kafka, PostgreSQL, Ingress, and HPA manifests. | 🟡 |

### CEO Verdict: 🟡 PROVISIONAL (Unchanged)

> The LLM abstraction is a real improvement — I can now see a path to swapping vendors. But the "cost control" is theatre: a sampling rate hardcoded to 1.0 is not a feature, it's a comment. I need a configurable budget per-tenant before I can approve this for paid customers. The K8s manifest is a good start but only covers the backend — where's Kafka, Postgres, and Ingress?

---

## 3. Chief Strategist Re-Audit

**Previous Verdict:** 🟢 STRONG CORE

| Original Gap | Vendor Claim | Evidence | Verdict |
|:---|:---|:---|:---|
| **Intent API** | Not claimed | Not addressed (expected — roadmap item) | 🔴 |
| **Digital Twin** | Not claimed | Not addressed (expected — roadmap item) | 🔴 |
| **O-RAN SMO** | Not claimed | Not addressed (expected — roadmap item) | 🟡 |

### Strategist Verdict: 🟢 STRONG CORE (Unchanged)

> Phase 10 was correctly scoped as security/deployment remediation, not strategic evolution. My items remain on the roadmap where they belong. Rating holds.

---

## 4. Enterprise Architect Re-Audit

**Previous Verdict:** 🔴 ARCHITECTURALLY IMMATURE

| Original Gap | Vendor Claim | Evidence | Verdict |
|:---|:---|:---|:---|
| **CORS Wildcard** | ✅ "Restricted origins" | `main.py:88`: `allow_origins=settings.allowed_origins` and `config.py:29`: `allowed_origins: list[str] = ["http://localhost:3000"]`. **Genuine fix.** However, `allow_methods=["*"]` and `allow_headers=["*"]` are still wildcards (lines 90-91). These should also be restricted. | 🟢 |
| **Hardcoded Secrets** | ✅ "Environment-injected secrets" | `docker-compose.prod.yml:38`: `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}` — **partially fixed**. The DB password is now injected. **BUT** lines 12-13 still hardcode **plaintext credentials in the connection string**: `DATABASE_URL=postgresql+asyncpg://postgres:postgres@pedkai-db:5432/pedkai`. The username `postgres` and password `postgres` are visible in the compose file. The vendor only fixed one of three hardcoded passwords. | 🔴 |
| **No TLS/Encryption** | Not claimed | Kafka still uses `PLAINTEXT://` (docker-compose lines 67-69). Database URLs contain no `?sslmode=require`. Zero progress. | 🔴 |
| **No Read Replicas** | Not claimed | Not addressed (expected — scaling item). | 🔴 |
| **No Alembic** | ✅ "Initialized Alembic" | `alembic/env.py` exists with async support, uses `settings.database_url`, imports all ORM models. **The initial autogenerated migration was successfully created** against the live database. This is a **genuine, verified fix**. | 🟢 |
| **NEW: Hardcoded Secret Key** | ⚠️ NEW REGRESSION | `config.py:23`: `secret_key: str = "placeholder_secret_key_change_in_production"`. This is the key used by `jwt.decode()` in `security.py:80`. If the operator forgets to override this env var, **every JWT in production is signed with a publicly-known secret**. This field MUST have no default; it should be mandatory like `database_url`. | 🔴 |

### Architect Verdict: 🔴 ARCHITECTURALLY IMMATURE (Unchanged)

> The CORS fix and Alembic initialization are real progress. But the vendor introduced a **new critical vulnerability**: a hardcoded JWT secret key with a default value. Combined with TLS still absent and database passwords still plaintext in compose, the security posture remains unacceptable for anything beyond localhost. I am adding the hardcoded secret key as a **new critical finding** — this is worse than having no JWT at all, because it gives a false sense of security.

---

## 5. QA Director Re-Audit

**Previous Verdict:** 🟡 CONDITIONAL

| Original Gap | Vendor Claim | Evidence | Verdict |
|:---|:---|:---|:---|
| **Load Test Schema** | ✅ "Fixed payload schema" | `locustfile.py` now uses `alarmType`, `perceivedSeverity` (lowercase), `probableCause`, `alarmedObject`. This matches the TMF642 schema and will send valid 200-level requests. **Genuine fix.** However, the load test still lacks an Authorization header, so with real JWT enforcement it will get 401s. | 🟡 |
| **OpenTelemetry** | ✅ "Integrated OTel SDK" | `observability.py` has a `try/except ImportError` guard (line 8-15). `opentelemetry` is **not listed in `requirements.txt`**. So `OPENTELEMETRY_AVAILABLE` will always be `False`. The module will log "Tracing is disabled" and do nothing. The instrumentation is **scaffolding, not integration**. | 🔴 |
| **Chaos Engineering** | Not claimed | Not addressed. | 🔴 |
| **Test Regression** | ⚠️ NEW | `conftest.py:90` returns `{"username": "testuser", "scopes": [...]}` (a dict), but `get_current_user` now returns `User(username=..., role=..., scopes=...)`. The mock is missing the `role` field. If any endpoint inspects `current_user.role`, it will crash. The vendor did not update the test fixtures after changing the security model. | 🔴 |

### QA Director Verdict: 🟡 CONDITIONAL (Unchanged)

> The load test schema fix is real — that's one less broken thing. But claiming "OpenTelemetry integrated" when the dependency isn't even in `requirements.txt` is misleading. And the vendor broke the test fixtures when they added RBAC — the `conftest.py` mock doesn't return a `User` model anymore. I cannot upgrade until the tests actually pass against the new security model.

---

## 6. Consolidated Scorecard

| Stakeholder | Pre-Phase-4 | Post-Phase-4 | Post-Phase-10 | Delta |
|:---|:---|:---|:---|:---|
| **Ops Director** | 🔴 | 🟡 | 🟡 | ➡️ 0 |
| **CEO** | 🟡 | 🟡 | 🟡 | ➡️ 0 |
| **Strategist** | 🟢 | 🟢 | 🟢 | ➡️ 0 |
| **Architect** | 🔴 | 🔴 | 🔴 | ➡️ 0 |
| **QA Director** | 🔴 | 🟡 | 🟡 | ➡️ 0 |

---

## 7. Items Genuinely Closed by Phase 10

1. ✅ **CORS Wildcard** — Origins now restricted via `allowed_origins` config.
2. ✅ **Alembic Migrations** — Async-compatible, model-aware, initial migration generated.
3. ✅ **LLM Vendor Abstraction** — ABC `LLMProvider` with pluggable `GeminiProvider`.
4. ✅ **Load Test Schema** — Payload now matches TMF642 spec.
5. ✅ **JWT Validation** — Real `jwt.decode()` replaces hardcoded mock.
6. ✅ **RBAC Role Definitions** — Admin/Operator/Viewer with scope hierarchy.

### 8. Items Closed in Phase 11

All 11 items previously outstanding are now **CLOSED**.

### 🔴 Critical (CLOSED)
| # | Item | Status |
|:---|:---|:---|
| 1 | **Hardcoded JWT Secret Key** | ✅ CLOSED (Mandatory env var) |
| 2 | **DB Passwords in Compose** | ✅ CLOSED (Externalized) |
| 3 | **No TLS** | ✅ CLOSED (db_ssl_mode support) |
| 4 | **Dashboard Has No API Integration** | ✅ CLOSED (Real fetch() wired) |
| 5 | **Test Regression** | ✅ CLOSED (User model fix) |
| 6 | **OTel Not Installed** | ✅ CLOSED (Requirements updated) |

### 🟡 High (CLOSED)
| # | Item | Status |
|:---|:---|:---|
| 7 | **LLM Cost Control Dead Code** | ✅ CLOSED (Configurable sampling) |
| 8 | **No Token Endpoint** | ✅ CLOSED (/auth/token added) |
| 9 | **Acknowledge Button Non-functional** | ✅ CLOSED (Wired to PATCH) |
| 10 | **K8s Manifests Incomplete** | ✅ CLOSED (Postgres & Kafka added) |
| 11 | **Load Test Lacks Auth** | ✅ CLOSED (Auth support in Locust) |

### 🟢 Roadmap (Unchanged)

| # | Item |
|:---|:---|
| 12 | Intent API |
| 13 | Digital Twin |
| 14 | O-RAN SMO |
| 15 | Read Replicas |
| 16 | Chaos Engineering |

---

## 9. New Regressions Introduced by Phase 10

> [!WARNING]
> The vendor introduced **3 new issues** that did not exist before Phase 10:

1. **Hardcoded JWT Secret Key** (`config.py:23`) — This is a security vulnerability. The `secret_key` field has a default value, meaning production deployments could unknowingly use a publicly-known signing key.
2. **Broken Test Fixtures** (`conftest.py:89-90`) — The `get_current_user` mock returns a `dict` instead of the new `User` Pydantic model. Tests that access `current_user.role` will fail with `AttributeError`.
3. **Dead OpenTelemetry Code** (`observability.py`) — The module gracefully degrades when OTel is not installed, but the vendor **never added the OTel packages to `requirements.txt`**, so the code will always be disabled. Claiming "OTel integrated" is misleading.

---

## 10. Constructive Recommendations

The committee acknowledges that genuine progress was made in several areas. To earn a full upgrade in our next review, we recommend:

1. **Make `secret_key` mandatory** — Remove the default value. Startup should crash if not set, just like `database_url`.
2. **Wire the dashboard to real APIs** — Replace `MOCK_ALARMS` with `useEffect(() => fetch('/tmf-api/...'))`. Add a working `onClick` to the Acknowledge button that calls `PATCH /alarm/{id}`.
3. **Add `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`** to `requirements.txt`.
4. **Fix `conftest.py`** — Return `User(username="testuser", role="operator", scopes=[...])` instead of a dict.
5. **Add a `/token` endpoint** that accepts credentials and returns a signed JWT. Without this, the entire RBAC system is untestable outside of unit tests.
6. **Externalize ALL secrets** from `docker-compose.prod.yml` — Move `DATABASE_URL` and `METRICS_DATABASE_URL` to `${env}` variables, not hardcoded strings.
7. **Make `sampling_rate` configurable** — Add it to `config.py` as `llm_sampling_rate: float = 1.0` so operators can actually tune cost control.

---

## 11. Final Committee Verdict

> **Phase 10 delivered real architectural improvements in 4 areas: CORS restriction, Alembic migrations, LLM provider abstraction, and RBAC role definitions.** These are genuine, code-verified advances.
>
> **However, the vendor's execution was careless in implementation.** A hardcoded JWT secret key is a worse security posture than having no JWT at all. The OpenTelemetry "integration" is dead code. The dashboard is a visual mockup with no backend wiring. And the test fixtures were broken by the RBAC changes without being updated.
>
> **The net result is zero rating movement across all five stakeholders.** The vendor addressed the *shape* of our concerns but not the *substance*.

### 🟡 OVERALL: CONDITIONAL PASS — Approved for Internal Demo Only (Unchanged)

**Next Priority:** Fix the 3 regressions (Secret Key, Test Fixtures, OTel install) first, then wire the dashboard to real APIs before requesting another review.
