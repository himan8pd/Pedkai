# Pedkai — Agentic Development Plan v2
# Incorporating Committee Reassessment (18 Feb 2026)

**Supersedes**: `agentic_development_plan.md` (17 Feb 2026)  
**Source documents**:
- `committee_reassessment_feb2026.md` — 5 BLOCKER, 10 HIGH, 8 MEDIUM findings; 16 of 26 mandatory amendments not started
- `agentic_development_plan.md` — original 5-layer plan (tasks carried forward where still valid)

**How to use**: Give any single task block (everything between two `---` separators) as a prompt to an AI coding agent. Each block is self-contained: it specifies the exact file(s) to touch, the exact change to make, and a verification command. Do not give an agent more than one task block at a time.

> [!IMPORTANT]
> **Execution order is mandatory.** Complete ALL tasks in a layer before starting the next. Within a layer, tasks are independent and can run in parallel. The system must remain runnable after every completed layer.

> [!CAUTION]
> **Layer 0 tasks are security emergencies.** They must be completed before any demo, any external access, and before any other layer begins. Failure to complete Layer 0 first means live credentials remain exposed and customer PII is being sent to Google unredacted.

---

## Layer Dependency Map

```
Layer 0 (Emergency Hotfixes — 48h)
  └─► Layer 1 (Security Hardening — 1 week)
        └─► Layer 2 (Data Integrity Fixes — 1 week)
              ├─► Layer 3 (LLM Pipeline Overhaul — 2 weeks)
              ├─► Layer 4 (Real-time Push — 2 weeks)
              └─► Layer 5 (Frontend Decomposition — 2 weeks)
                    └─► Layer 6 (Governance & Docs — parallel with 3-5)
                          └─► Layer 7 (Mandatory Amendments — before pilot)
                                └─► Layer 8 (Verification & Load Tests — before pilot)
```

Within each layer, all tasks are **fully independent** and can be parallelised.

---

## Global Rules (apply to every task)

1. **Import paths**: All Python imports use `from backend.app.xxx import yyy`. Project root is `Pedkai/`.
2. **Async**: All DB operations use `async/await` with `AsyncSession`.
3. **SQLite compatibility**: No PostgreSQL-specific types in test-facing code. Use `String` not `UUID` column types, `JSON` not `JSONB`.
4. **Minimal diffs**: When modifying an existing file, make the **smallest possible change**. Show exact lines to add/replace. Never reformat surrounding code.
5. **No circular imports**: Services → schemas/models only. Routers → services/schemas only. Nothing imports from routers.
6. **Test harness**: All tests use fixtures from `tests/conftest.py`. Override `get_current_user` per-test for scope changes.
7. **Working directory**: All `cd` commands use `/Users/himanshu/Projects/Pedkai`.

---

## Layer 0 — Emergency Hotfixes (complete within 48 hours, before anything else)

These fix active security vulnerabilities and runtime crashes. The system is currently broken or insecure in these ways. Do not start Layer 1 until all Layer 0 tasks pass verification.

---

### Task 0.1 — Remove .env from Git Tracking

**Committee finding**: B-1 (BLOCKER)  
**What**: The `.env` file containing live API keys is tracked by git. Untrack it without deleting it.

**File to modify**: `.gitignore` (verify `.env` is listed — it is, on line 41)  
**Command to run** (not a code change — a git operation):

```bash
cd /Users/himanshu/Projects/Pedkai
git rm --cached .env
git commit -m "security: stop tracking .env — contains live credentials (B-1)"
```

**Then create** `.env.example` as a safe template:

**File to create**: `.env.example`

```bash
# Pedkai Environment Configuration Template
# Copy to .env and fill in real values. NEVER commit .env to git.

APP_NAME=Pedkai
APP_VERSION=0.1.0
DEBUG=false

API_PREFIX=/api/v1
PEDKAI_BACKEND_PORT=8000
PEDKAI_FRONTEND_PORT=3000

# Database (PostgreSQL)
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@localhost:5432/pedkai

# Database (TimescaleDB - KPI Metrics)
METRICS_DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@localhost:5433/pedkai_metrics

# Gemini LLM — get key from https://makersuite.google.com/app/apikey
GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE
GEMINI_MODEL=gemini-2.0-flash

# Kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_CONSUMER_GROUP=pedkai-consumers

# Multi-tenancy
DEFAULT_TENANT_ID=default

# Vector embeddings
EMBEDDING_DIMENSION=3072

# HuggingFace (for gated datasets)
HF_TOKEN=YOUR_HF_TOKEN_HERE

# Kaggle API
KAGGLE_USERNAME=YOUR_KAGGLE_USERNAME
KAGGLE_KEY=YOUR_KAGGLE_KEY

# Security — generate with: openssl rand -hex 32
SECRET_KEY=GENERATE_WITH_OPENSSL_RAND_HEX_32
ADMIN_PASSWORD=CHANGE_ME_STRONG_PASSWORD
OPERATOR_PASSWORD=CHANGE_ME_STRONG_PASSWORD

# Frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
FRONTEND_URL=http://localhost:3000
BACKEND_URL=http://localhost:8000

# LLM Provider (gemini | on-prem)
PEDKAI_LLM_PROVIDER=gemini
```

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
git status | grep ".env"
# Expected: .env should appear as "untracked" not "tracked"
python -c "
import subprocess
result = subprocess.run(['git', 'ls-files', '.env'], capture_output=True, text=True)
assert result.stdout.strip() == '', f'FAIL: .env is still tracked: {result.stdout}'
print('✅ .env untracked from git')
"
```

---

### Task 0.2 — Wire PII Scrubber into LLM Service

**Committee finding**: B-2 (BLOCKER)  
**What**: `PIIScrubber` exists in `pii_scrubber.py` but is never called before prompts are sent to Gemini. Every LLM call currently sends raw customer PII to Google. Fix `llm_service.py` to scrub before prompt construction.

**File to modify**: `backend/app/services/llm_service.py`

**Step 1** — Add import at the top of the file (after existing imports):
```python
from backend.app.services.pii_scrubber import PIIScrubber
```

**Step 2** — Add scrubber instantiation to `LLMService.__init__` (or `GeminiProvider.__init__`). Find the `__init__` method and add:
```python
self._pii_scrubber = PIIScrubber()
```

**Step 3** — In `generate_explanation()` and `generate_sitrep()`, find the line where `prompt = f"""..."""` is constructed. Immediately **after** the prompt string is assembled and **before** it is passed to the LLM client, add:

```python
# B-2 FIX: Scrub PII before sending to external LLM
prompt, scrub_manifest = self._pii_scrubber.scrub(prompt)
if scrub_manifest:
    logger.info(
        f"PII scrubber removed {len(scrub_manifest)} items before LLM call. "
        f"Prompt hash: {hashlib.sha256(prompt.encode()).hexdigest()[:16]}"
    )
```

**Step 4** — Return the `scrub_manifest` alongside the LLM response so callers can store it in the audit trail. Modify the return value of both methods to include `scrub_manifest` — either as a tuple `(text, scrub_manifest)` or by adding it to the existing response dict/object. Choose whichever approach matches the current return type.

**Important context**: `PIIScrubber.scrub(text)` returns `(scrubbed_text: str, manifest: list[dict])`. The manifest contains `{field_type, original_value_hash, replacement}` per scrubbed item — it does NOT contain the original PII values.

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
import ast, sys
with open('backend/app/services/llm_service.py') as f:
    src = f.read()
assert 'PIIScrubber' in src, 'FAIL: PIIScrubber not imported'
assert 'pii_scrubber' in src.lower(), 'FAIL: pii_scrubber not referenced'
assert '_pii_scrubber' in src or 'scrubber' in src, 'FAIL: scrubber not instantiated'
print('✅ PII scrubber wired into llm_service.py')
"
```

---

### Task 0.3 — Fix Audit Trail Tenant Isolation

**Committee finding**: H-5 (HIGH — cross-tenant data leak in most sensitive endpoint)  
**What**: `get_audit_trail()` in `incidents.py` calls `_get_or_404(db, incident_id)` without `tenant_id`, allowing any tenant to read any other tenant's audit trail.

**File to modify**: `backend/app/api/incidents.py`

**Find this exact pattern** (the audit trail endpoint — search for the function containing `get_audit_trail` or the route `/{incident_id}/audit-trail`):
```python
incident = await _get_or_404(db, incident_id)
```

**Replace with**:
```python
incident = await _get_or_404(db, incident_id, current_user.tenant_id)
```

**Important**: Only change the call inside the audit trail endpoint function. All other endpoint functions already pass `current_user.tenant_id` correctly — do not touch them.

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
import re
with open('backend/app/api/incidents.py') as f:
    src = f.read()
# Find all _get_or_404 calls and ensure none are missing tenant_id
bare_calls = re.findall(r'_get_or_404\(db,\s*incident_id\)', src)
assert len(bare_calls) == 0, f'FAIL: {len(bare_calls)} _get_or_404 calls missing tenant_id: {bare_calls}'
print('✅ All _get_or_404 calls include tenant_id')
"
```

---

### Task 0.4 — Fix Service Impact Tenant Isolation

**Committee finding**: H-9 (HIGH — all service-impact endpoints expose cross-tenant data)  
**What**: The `/clusters`, `/noise-wall`, and `/deep-dive/{cluster_id}` endpoints in `service_impact.py` query without `WHERE tenant_id = :tid`.

**File to modify**: `backend/app/api/service_impact.py`

**Step 1** — In `get_alarm_clusters()`: find the SQL query against `decision_traces`. Add tenant filtering:

Find:
```python
result = await db.execute(
    text("""
        SELECT id, title, severity, status, entity_id, created_at
        FROM decision_traces
        ORDER BY created_at DESC
        LIMIT 200
    """)
)
```

Replace with:
```python
tid = current_user.tenant_id or "default"
result = await db.execute(
    text("""
        SELECT id, title, severity, status, entity_id, created_at
        FROM decision_traces
        WHERE tenant_id = :tid
        ORDER BY created_at DESC
        LIMIT 200
    """),
    {"tid": tid}
)
```

**Step 2** — Apply the same pattern to `get_noise_wall()` — same query, same fix.

**Step 3** — In `get_cluster_deep_dive()`: the function currently uses `select(DecisionTraceORM)` but `DecisionTraceORM` is **never imported**. Fix the import AND add tenant filtering:

Add to imports at top of file:
```python
from backend.app.models.decision_trace import DecisionTrace as DecisionTraceORM
```
(Check the actual model class name in `backend/app/models/` — use whatever the correct ORM class is. If it is named differently, use that name.)

Then in the query inside `get_cluster_deep_dive()`, add a `.where(DecisionTraceORM.tenant_id == current_user.tenant_id)` filter.

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
with open('backend/app/api/service_impact.py') as f:
    src = f.read()
# Check tenant filtering exists in cluster query
assert 'WHERE tenant_id = :tid' in src or 'tenant_id' in src, 'FAIL: no tenant filtering'
# Check DecisionTraceORM is imported
assert 'DecisionTrace' in src or 'decision_trace' in src.lower(), 'FAIL: DecisionTraceORM not imported'
print('✅ Service impact tenant isolation fixed')
"
# Also verify the module imports cleanly (catches NameError)
python -c "from backend.app.api.service_impact import router; print('✅ service_impact.py imports without error')"
```

---

### Task 0.5 — Fix GeminiAdapter Async (Event Loop Blocker)

**Committee finding**: M-4 (MEDIUM — blocks entire FastAPI event loop during LLM calls)  
**What**: `GeminiAdapter.generate()` in `llm_adapter.py` uses the synchronous Gemini client (`client.models.generate_content()`). In an async FastAPI app this blocks the event loop. Fix to use the async client.

**File to modify**: `backend/app/services/llm_adapter.py`

Find in `GeminiAdapter.generate()`:
```python
from google import genai
client = genai.Client(api_key=self.config.api_key)
response = client.models.generate_content(
    model=self.config.model_name,
    contents=prompt,
)
```

Replace with:
```python
from google import genai
client = genai.Client(api_key=self.config.api_key)
response = await client.aio.models.generate_content(
    model=self.config.model_name,
    contents=prompt,
)
```

Also ensure the method signature is `async def generate(...)` — it should already be, but verify.

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
with open('backend/app/services/llm_adapter.py') as f:
    src = f.read()
assert 'client.aio.models.generate_content' in src, 'FAIL: still using sync client'
assert 'client.models.generate_content' not in src, 'FAIL: sync call still present'
print('✅ GeminiAdapter uses async client')
"
```

---

### Task 0.6 — Clean Dead Code in llm_service.py

**Committee finding**: H-7 (HIGH — dead code from incomplete refactor creates confusion and maintenance risk)  
**What**: Remove the two orphaned `pass` blocks in the sampling logic and the duplicate `should_bypass_sampling = False` assignment.

**File to modify**: `backend/app/services/llm_service.py`

**Find and remove** this dead block (around lines 113–118):
```python
if random.random() > self.sampling_rate:
    pass  # does nothing
else:
    pass  # does nothing
```

**Find and remove** the duplicate assignment (around line 142):
```python
should_bypass_sampling = False  # Duplicate of line 121
```

Keep the first `should_bypass_sampling` assignment and the actual sampling logic that follows it. Only remove the dead/duplicate code.

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
with open('backend/app/services/llm_service.py') as f:
    lines = f.readlines()
dead = [i+1 for i,l in enumerate(lines) if l.strip() == 'pass  # does nothing' or l.strip() == 'pass # does nothing']
assert len(dead) == 0, f'FAIL: dead pass blocks still at lines {dead}'
print('✅ Dead code removed from llm_service.py')
"
```

---

## Layer 1 — Security Hardening (1 week, after Layer 0)

---

### Task 1.1 — Replace Mock Auth with Real User Database

**Committee finding**: B-3 (BLOCKER)
**What**: `auth.py` uses a hardcoded 2-user dict with plaintext password comparison. Replace with a real `users` table and bcrypt hashing.

**Files to create**:
- `backend/app/models/user_orm.py`
- `backend/app/services/auth_service.py`

**File to modify**: `backend/app/api/auth.py`

**`backend/app/models/user_orm.py`** — create with this content:
```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime
from backend.app.core.database import Base

class UserORM(Base):
    __tablename__ = "users"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)
    tenant_id = Column(String(50), nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
```

**`backend/app/services/auth_service.py`** — create with this content:
```python
import logging, os
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from passlib.context import CryptContext
from backend.app.models.user_orm import UserORM

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

async def get_user_by_username(db: AsyncSession, username: str) -> Optional[UserORM]:
    result = await db.execute(select(UserORM).where(UserORM.username == username))
    return result.scalar_one_or_none()

async def authenticate_user(db: AsyncSession, username: str, password: str) -> Optional[UserORM]:
    user = await get_user_by_username(db, username)
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user

async def seed_default_users(db: AsyncSession) -> None:
    """Seed 4 default users on first startup. Passwords from env vars."""
    from backend.app.core.security import Role
    existing = await db.execute(select(UserORM).limit(1))
    if existing.scalar_one_or_none():
        return
    users = [
        UserORM(username="admin", hashed_password=hash_password(os.getenv("ADMIN_PASSWORD","CHANGE_ME")),
                role=Role.ADMIN, tenant_id="default"),
        UserORM(username="operator", hashed_password=hash_password(os.getenv("OPERATOR_PASSWORD","CHANGE_ME")),
                role=Role.OPERATOR, tenant_id="default"),
        UserORM(username="shift_lead", hashed_password=hash_password(os.getenv("SHIFT_LEAD_PASSWORD","CHANGE_ME")),
                role=Role.SHIFT_LEAD, tenant_id="default"),
        UserORM(username="engineer", hashed_password=hash_password(os.getenv("ENGINEER_PASSWORD","CHANGE_ME")),
                role=Role.ENGINEER, tenant_id="default"),
    ]
    db.add_all(users)
    await db.commit()
    logger.info("Seeded 4 default users")
```

**Modify `backend/app/api/auth.py`**:
- Remove `MOCK_USERS_DB` dict entirely
- Add `db: AsyncSession = Depends(get_db)` to the `/token` endpoint
- Replace plaintext password check with `await auth_service.authenticate_user(db, username, password)`
- Build scopes from `ROLE_SCOPES[Role(user.role)]`

**Add to `backend/requirements.txt`**: `passlib[bcrypt]>=1.7.4`

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
with open('backend/app/api/auth.py') as f: src = f.read()
assert 'MOCK_USERS_DB' not in src, 'FAIL: mock db still present'
from backend.app.services.auth_service import hash_password, verify_password
h = hash_password('test')
assert verify_password('test', h)
print('✅ Real auth system in place')
"
```

---

### Task 1.2 — Fix Proactive Comms Consent Default (GDPR)

**Committee finding**: H-10
**What**: Line 69 of `proactive_comms.py` defaults `consent_proactive_comms` to `True`. GDPR requires explicit opt-in — default must be `False`.

**File to modify**: `backend/app/services/proactive_comms.py`

Find:
```python
return getattr(customer, "consent_proactive_comms", True)
```
Replace with:
```python
return getattr(customer, "consent_proactive_comms", False)  # GDPR: explicit opt-in required
```

**Also add column to CustomerORM** if missing — in `backend/app/models/customer_orm.py`:
```python
consent_proactive_comms = Column(Boolean, default=False, nullable=False)
```

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
with open('backend/app/services/proactive_comms.py') as f: src = f.read()
assert 'consent_proactive_comms\", False' in src or \"consent_proactive_comms', False\" in src, 'FAIL'
print('✅ Consent defaults to False (GDPR compliant)')
"
```

---

### Task 1.3 — Fix Emergency Service Detection

**Committee finding**: M-6
**What**: Emergency service detection uses `"EMERGENCY" in entity_external_id.upper()` — too broad and misses real emergency gateways. Fix to query `entity_type = 'EMERGENCY_SERVICE'` from the topology graph.

**File to modify**: `backend/app/api/incidents.py`

Find the block containing `"EMERGENCY" in entity_external_id.upper()` and replace with:
```python
is_emergency = False
if entity_id:
    try:
        from sqlalchemy import text as sql_text
        es_check = await db.execute(
            sql_text("SELECT 1 FROM network_entities WHERE id = :eid AND entity_type = 'EMERGENCY_SERVICE' LIMIT 1"),
            {"eid": str(entity_id)}
        )
        is_emergency = es_check.scalar() is not None
    except Exception as e:
        logger.warning(f"Emergency service check failed: {e}")
        is_emergency = False
```

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
with open('backend/app/api/incidents.py') as f: src = f.read()
assert '\"EMERGENCY\" in entity_external_id.upper()' not in src, 'FAIL: string matching still present'
assert 'EMERGENCY_SERVICE' in src, 'FAIL: entity_type check not added'
print('✅ Emergency detection uses entity_type')
"
```

---

### Task 1.4 — Fix BSS N+1 Query

**Committee finding**: M-7
**What**: `bss_adapter.py` calls `get_account_by_customer_id()` in a loop — 50 customers = 50 queries. Replace with a single `IN (...)` batch query.

**File to modify**: `backend/app/services/bss_adapter.py`

Replace the `for cid in customer_ids:` loop in `get_revenue_at_risk()` with:
```python
if not customer_ids:
    return RevenueResult()
from sqlalchemy import text as sql_text
id_strs = [str(cid) for cid in customer_ids]
placeholders = ", ".join(f":id_{i}" for i in range(len(id_strs)))
params = {f"id_{i}": id_strs[i] for i in range(len(id_strs))}
result = await self._service.session.execute(
    sql_text(f"SELECT ba.customer_id, sp.monthly_fee FROM bss_accounts ba "
             f"LEFT JOIN service_plans sp ON ba.service_plan_id = sp.id "
             f"WHERE ba.customer_id IN ({placeholders})"),
    params
)
rows = {str(r[0]): r[1] for r in result.fetchall()}
priced = [cid for cid in id_strs if rows.get(cid) is not None]
unpriced = [cid for cid in id_strs if rows.get(cid) is None]
total = sum(float(rows[cid]) for cid in priced) if priced else None
return RevenueResult(
    total_revenue_at_risk=total,
    priced_customer_count=len(priced),
    unpriced_customer_count=len(unpriced),
    requires_manual_valuation=len(unpriced) > 0,
)
```

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
with open('backend/app/services/bss_adapter.py') as f: src = f.read()
assert 'for cid in customer_ids' not in src, 'FAIL: N+1 loop still present'
assert 'IN (' in src or 'placeholders' in src, 'FAIL: batch query not added'
print('✅ BSS uses batched query')
"
```

---

### Task 1.5 — Add Depth Limit to CX Intelligence CTE

**Committee finding**: M-8
**What**: Recursive CTE in `cx_intelligence.py` has no depth limit — can exhaust memory on cyclic graphs.

**File to modify**: `backend/app/services/cx_intelligence.py`

Find the `WITH RECURSIVE downstream_impact AS` block and replace with:
```sql
WITH RECURSIVE downstream_impact AS (
    SELECT to_entity_id, 1 AS depth
    FROM topology_relationships
    WHERE from_entity_id = :site_id AND tenant_id = :tid
    UNION ALL
    SELECT tr.to_entity_id, di.depth + 1
    FROM topology_relationships tr
    INNER JOIN downstream_impact di ON tr.from_entity_id = di.to_entity_id
    WHERE di.depth < :max_depth AND tr.tenant_id = :tid
)
SELECT DISTINCT to_entity_id FROM downstream_impact LIMIT 1000
```

Pass `max_depth=5` and `tid=tenant_id` as query parameters alongside `:site_id`.

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
with open('backend/app/services/cx_intelligence.py') as f: src = f.read()
assert 'max_depth' in src or 'depth <' in src, 'FAIL: no depth limit'
assert 'LIMIT 1000' in src, 'FAIL: no row limit'
print('✅ CX intelligence CTE has depth limit')
"
```

---


## Layer 2 — Data Integrity Fixes (1 week, parallel with Layer 1, after Layer 0)

---

### Task 2.1 — Fix Scorecard: Remove Fabricated Baselines

**Committee finding**: B-4 (BLOCKER)
**What**: `autonomous.py` scorecard uses hardcoded magic numbers for non-Pedkai zone metrics. Replace with honest nulls.

**File to modify**: `backend/app/api/autonomous.py`

**Step 1** — Delete these constants:
```python
BASELINE_NON_PEDKAI_MTTR = 180.0
BASELINE_INCIDENT_RATIO = 2.4
```

**Step 2** — Replace the block that computes `non_pedkai_zone_incident_count`, `revenue_protected`, `incidents_prevented`, `uptime_gained_minutes` with:
```python
# B-4 FIX: No fabricated baselines. Shadow-mode data collection required first.
non_pedkai_zone_mttr = None
non_pedkai_zone_incident_count = None
revenue_protected = None
incidents_prevented = None
uptime_gained_minutes = None
confidence_interval = None
baseline_status = "pending_shadow_mode_collection"
baseline_note = (
    "Non-Pedkai zone baseline requires 30-day shadow-mode deployment. "
    "See docs/shadow_mode.md for the approved methodology."
)
```

**Step 3** — Fix MTTR fallback. Find:
```python
avg_mttr = (total_minutes / closed_count) if closed_count > 0 else 45.0
```
Replace with:
```python
avg_mttr = (total_minutes / closed_count) if closed_count > 0 else None
```

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
with open('backend/app/api/autonomous.py') as f: src = f.read()
assert 'BASELINE_NON_PEDKAI_MTTR' not in src, 'FAIL: fabricated constant present'
assert 'BASELINE_INCIDENT_RATIO' not in src, 'FAIL: fabricated ratio present'
assert '2500.0' not in src, 'FAIL: arbitrary revenue multiplier present'
assert 'pending_shadow_mode_collection' in src, 'FAIL: honest status not added'
print('✅ Scorecard uses honest nulls')
"
```

---

### Task 2.2 — Fix Deep-Dive: Dynamic Reasoning Chain

**Committee finding**: B-5 (BLOCKER)
**What**: `service_impact.py` `get_cluster_deep_dive()` returns hardcoded reasoning steps and `noise_reduction_pct: 82.5` for every cluster. Also has a `NameError` — `DecisionTraceORM` is never imported.

**File to modify**: `backend/app/api/service_impact.py`

**Step 1** — Add import (check actual model path first with `find /Users/himanshu/Projects/Pedkai/backend/app/models -name "*.py" | xargs grep -l "DecisionTrace"`):
```python
from backend.app.models.decision_trace import DecisionTrace as DecisionTraceORM
```

**Step 2** — Replace the entire `get_cluster_deep_dive` function body with:
```python
tid = current_user.tenant_id or "default"
try:
    from sqlalchemy import select as sa_select
    result = await db.execute(
        sa_select(DecisionTraceORM)
        .where(DecisionTraceORM.tenant_id == tid)
        .limit(20)
    )
    traces = result.scalars().all()
except Exception as e:
    logger.warning(f"Deep-dive query failed: {e}")
    traces = []

total = len(traces)
alarm_types = list({getattr(t, 'trigger_type', 'UNKNOWN') for t in traces}) or ["UNKNOWN"]
noise_reduction = round(((total - 1) / total * 100) if total > 1 else 0.0, 1)
confidence = round(min(0.5 + (total / 20), 0.95), 2)

reasoning_chain = [{
    "step": 1,
    "description": f"Temporal clustering: {total} events of type(s): {', '.join(alarm_types[:3])}.",
    "confidence": confidence,
    "source": "alarm_correlation:temporal_engine",
    "evidence_count": total,
}] if total > 0 else [{
    "step": 1,
    "description": "No alarm data available for this cluster in the current tenant scope.",
    "confidence": 0.0,
    "source": "alarm_correlation:temporal_engine",
    "evidence_count": 0,
}]

return {
    "cluster_id": cluster_id,
    "tenant_id": tid,
    "reasoning_chain": reasoning_chain,
    "noise_reduction_pct": noise_reduction,
    "total_alarms_analysed": total,
    "note": "Reasoning chain derived from actual cluster telemetry.",
}
```

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
with open('backend/app/api/service_impact.py') as f: src = f.read()
assert '82.5' not in src, 'FAIL: hardcoded 82.5 still present'
assert '0.94' not in src, 'FAIL: hardcoded confidence still present'
assert 'DecisionTrace' in src, 'FAIL: import not added'
print('✅ Deep-dive uses dynamic reasoning chain')
"
python -c "from backend.app.api.service_impact import router; print('✅ imports cleanly')"
```

---

### Task 2.3 — Fix Clusters Endpoint: Query Alarms Not Decision Traces

**Committee finding**: H-8
**What**: `get_alarm_clusters()` queries `decision_traces`. Decision traces are not alarms. Fix to query the actual alarms table.

**File to modify**: `backend/app/api/service_impact.py`

First, find the alarms table name:
```bash
grep -r "__tablename__" /Users/himanshu/Projects/Pedkai/backend/app/models/ | grep -i alarm
```

In `get_alarm_clusters()`, replace the `decision_traces` query with a query against the alarms table. Adapt column names to match the actual schema:
```python
tid = current_user.tenant_id or "default"
result = await db.execute(
    text("""
        SELECT id,
               specific_problem AS title,
               perceived_severity AS severity,
               ack_state AS status,
               alarmed_object_id AS entity_id,
               event_time AS created_at
        FROM alarms
        WHERE tenant_id = :tid
        ORDER BY event_time DESC
        LIMIT 200
    """),
    {"tid": tid}
)
```

> [!NOTE]
> If column names differ, adjust the aliases. The goal is to return: `id`, `title`, `severity`, `status`, `entity_id`, `created_at`.

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
import re
with open('backend/app/api/service_impact.py') as f: src = f.read()
fn = re.search(r'async def get_alarm_clusters.*?(?=\nasync def|\Z)', src, re.DOTALL)
if fn:
    assert 'decision_traces' not in fn.group(), 'FAIL: clusters still queries decision_traces'
print('✅ Clusters queries alarms table')
"
```

---

### Task 2.4 — Fix Topology Staleness Metric

**Committee finding**: M-5
**What**: Staleness is based on `created_at < yesterday`. Topology relationships don't change hourly — this produces false positives. Fix to use `last_synced_at` with a 7-day threshold.

**File to modify**: `backend/app/api/topology.py`

Find the staleness query containing `created_at < :yesterday` and replace with:
```python
from datetime import timedelta
staleness_threshold = datetime.now(timezone.utc) - timedelta(days=7)
stale_res = await db.execute(
    text("""
        SELECT COUNT(*) FROM topology_relationships
        WHERE tenant_id = :tid
        AND (last_synced_at IS NULL OR last_synced_at < :threshold)
    """),
    {"tid": tid, "threshold": staleness_threshold}
)
```

Also add `staleness_threshold_days: 7` to the health response payload.

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
with open('backend/app/api/topology.py') as f: src = f.read()
assert 'last_synced_at' in src or 'staleness_threshold' in src, 'FAIL: still uses created_at'
print('✅ Topology staleness uses sync time')
"
```

---


## Layer 3 — LLM Pipeline Overhaul (2 weeks, after Layer 2)

---

### Task 3.1 — Consolidate Dual LLM Abstractions

**Committee finding**: M-2
**What**: Two competing LLM abstraction patterns exist — `LLMProvider` (in `llm_service.py`) and `LLMAdapter` (in `llm_adapter.py`). `llm_adapter.py` has the better design (prompt hashing, model versioning, PII integration point) but is dead code. Wire `llm_service.py` to use `llm_adapter.py` and delete `LLMProvider`.

**Files to modify**:
- `backend/app/services/llm_service.py`
- `backend/app/services/llm_adapter.py` (already fixed to async in Task 0.5)

**Step 1** — In `llm_service.py`, remove the `LLMProvider` ABC class and the `GeminiProvider` class entirely.

**Step 2** — In `LLMService.__init__`, replace instantiation of `GeminiProvider` with:
```python
from backend.app.services.llm_adapter import get_adapter
self._adapter = get_adapter()  # Uses PEDKAI_LLM_PROVIDER env var
self._pii_scrubber = PIIScrubber()  # Already added in Task 0.2
```

**Step 3** — In `generate_explanation()` and `generate_sitrep()`, replace the direct Gemini client call with:
```python
response = await self._adapter.generate(prompt)
llm_text = response.get("text", "") if isinstance(response, dict) else str(response)
model_version = response.get("model_version", "unknown") if isinstance(response, dict) else "unknown"
prompt_hash = response.get("prompt_hash", "") if isinstance(response, dict) else ""
```

**Step 4** — Return `model_version` and `prompt_hash` alongside the LLM text so callers can store them in the incident audit trail (populating `llm_model_version` and `llm_prompt_hash` columns in `IncidentORM`).

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
with open('backend/app/services/llm_service.py') as f: src = f.read()
assert 'class LLMProvider' not in src, 'FAIL: LLMProvider ABC still present'
assert 'class GeminiProvider' not in src, 'FAIL: GeminiProvider still present'
assert 'get_adapter' in src or 'llm_adapter' in src, 'FAIL: adapter not wired in'
print('✅ Single LLM abstraction layer')
"
```

---

### Task 3.2 — Add LLM Confidence Scoring

**Committee finding**: H-2 (AI Director §2.5 mandate)
**What**: All LLM-generated recommendations must include a confidence score. Currently `generate_explanation()` returns a plain string with no confidence metadata.

**File to modify**: `backend/app/services/llm_service.py`

After receiving the LLM response text, add a confidence scoring step:

```python
def _compute_confidence(
    self,
    llm_text: str,
    decision_memory_hits: int,
    causal_evidence_count: int,
) -> float:
    """
    Compute a confidence score [0.0, 1.0] for an LLM output.
    Based on: decision memory similarity hits + causal evidence count.
    NOT based on LLM self-reported confidence (which is unreliable).
    """
    base = 0.3  # Minimum confidence for any LLM output
    memory_bonus = min(decision_memory_hits * 0.1, 0.4)   # Up to +0.4 for memory hits
    evidence_bonus = min(causal_evidence_count * 0.05, 0.3)  # Up to +0.3 for evidence
    score = base + memory_bonus + evidence_bonus
    return round(min(score, 0.95), 2)  # Cap at 0.95 — never claim certainty
```

Modify `generate_explanation()` to:
1. Accept `decision_memory_hits: int = 0` and `causal_evidence_count: int = 0` parameters
2. Call `self._compute_confidence(llm_text, decision_memory_hits, causal_evidence_count)`
3. Return a dict: `{"text": llm_text, "confidence": confidence_score, "model_version": ..., "ai_generated": True}`

Add a configurable fallback threshold to `config.py`:
```python
llm_confidence_threshold: float = 0.5  # Below this, use template fallback
```

If confidence is below threshold, return a structured template instead of the LLM text:
```python
if confidence < settings.llm_confidence_threshold:
    llm_text = (
        f"[LOW CONFIDENCE — TEMPLATE FALLBACK]\n"
        f"Anomaly detected on entity {entity_id}. "
        f"Insufficient historical data for AI analysis. "
        f"Manual investigation recommended."
    )
```

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
with open('backend/app/services/llm_service.py') as f: src = f.read()
assert '_compute_confidence' in src, 'FAIL: confidence scoring not added'
assert 'ai_generated' in src, 'FAIL: ai_generated flag not added'
assert 'llm_confidence_threshold' in src or 'confidence_threshold' in src, 'FAIL: threshold not added'
print('✅ LLM confidence scoring added')
"
```

---

### Task 3.3 — Add AI-Generated Watermarks to API Responses

**Committee finding**: H-3 (Legal Counsel §2.14 mandate)
**What**: All LLM-sourced API responses must include `"ai_generated": true` and `"ai_watermark"` fields. The frontend must render a visible `[AI Generated]` badge.

**Files to modify**:
- `backend/app/api/incidents.py` — add watermark to SITREP response
- `backend/app/api/service_impact.py` — add watermark to deep-dive response
- `backend/app/api/autonomous.py` — add watermark to detections response
- `frontend/app/page.tsx` — render `[AI Generated]` badge

**Backend changes** — in each endpoint that returns LLM-generated content, add to the response dict:
```python
"ai_generated": True,
"ai_watermark": "This content was generated by Pedkai AI (Gemini). It is advisory only and requires human review before action.",
"ai_model_version": model_version,  # from LLM adapter response
```

**Frontend change** — in `page.tsx`, find the SITREP panel (around line 404):
```tsx
<h3 className="text-cyan-400 text-xs font-black uppercase tracking-widest">Autonomous SITREP</h3>
```
Add immediately after:
```tsx
<span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-amber-500/20 text-amber-400 border border-amber-500/30">
  🤖 AI Generated — Advisory Only
</span>
```

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
with open('backend/app/api/incidents.py') as f: src = f.read()
assert 'ai_generated' in src, 'FAIL: ai_generated not in incidents.py'
with open('frontend/app/page.tsx') as f: src = f.read()
assert 'AI Generated' in src, 'FAIL: AI watermark not in frontend'
print('✅ AI watermarks added to backend and frontend')
"
```

---

### Task 3.4 — Populate llm_model_version and llm_prompt_hash in Incident Audit Trail

**Committee finding**: Amendment #7 (partial — columns exist but are never populated)
**What**: `IncidentORM` has `llm_model_version` and `llm_prompt_hash` columns but they are always `None`. Populate them when generating SITREPs.

**File to modify**: `backend/app/api/incidents.py`

In the SITREP generation endpoint (the one that calls `llm_service.generate_explanation()` or `generate_sitrep()`):

After receiving the LLM response, update the incident record:
```python
# Populate audit trail fields — Amendment #7
llm_response = await llm_service.generate_sitrep(...)  # returns dict now (Task 3.1)
incident.llm_model_version = llm_response.get("model_version", "unknown")
incident.llm_prompt_hash = llm_response.get("prompt_hash", "")
incident.sitrep_text = llm_response.get("text", "")
await db.commit()
```

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
with open('backend/app/api/incidents.py') as f: src = f.read()
assert 'llm_model_version' in src, 'FAIL: model version not populated'
assert 'llm_prompt_hash' in src, 'FAIL: prompt hash not populated'
print('✅ Audit trail populated with LLM metadata')
"
```

---


## Layer 4 — Real-time Push (2 weeks, after Layer 2, parallel with Layer 3)

---

### Task 4.1 — Add SSE Endpoint for Real-time Alarm Push

**Committee finding**: H-4 (CTO §2.3 mandate)
**What**: Frontend polls every 10 seconds. Replace with Server-Sent Events (SSE) for real-time push. SSE is simpler than WebSockets for one-directional server→client push and requires no new infrastructure.

**File to create**: `backend/app/api/sse.py`

```python
"""
Server-Sent Events (SSE) endpoint for real-time alarm and incident push.
Replaces the 10-second polling loop in the frontend.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from backend.app.core.database import get_db
from backend.app.core.security import get_current_user, User

logger = logging.getLogger(__name__)
router = APIRouter()


async def alarm_event_generator(request: Request, db: AsyncSession, tenant_id: str):
    """Generate SSE events for new alarms. Polls DB every 2s (server-side, not client-side)."""
    last_seen_id = None
    while True:
        if await request.is_disconnected():
            logger.info(f"SSE client disconnected for tenant {tenant_id}")
            break
        try:
            query = text("""
                SELECT id, specific_problem, perceived_severity, alarmed_object_id, event_time
                FROM alarms
                WHERE tenant_id = :tid
                ORDER BY event_time DESC
                LIMIT 20
            """)
            result = await db.execute(query, {"tid": tenant_id})
            rows = result.fetchall()
            if rows:
                newest_id = str(rows[0][0])
                if newest_id != last_seen_id:
                    last_seen_id = newest_id
                    payload = {
                        "event": "alarms_updated",
                        "tenant_id": tenant_id,
                        "count": len(rows),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
        except Exception as e:
            logger.error(f"SSE generator error: {e}")
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"
        await asyncio.sleep(2)  # Server polls every 2s — client stays connected


@router.get("/stream/alarms")
async def stream_alarms(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SSE endpoint: streams alarm update notifications to connected clients."""
    return StreamingResponse(
        alarm_event_generator(request, db, current_user.tenant_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
```

**Register in `backend/app/main.py`** — add after existing router registrations:
```python
from backend.app.api import sse
app.include_router(sse.router, prefix=f"{settings.api_prefix}", tags=["Real-time SSE"])
```

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
from backend.app.api.sse import router
routes = [r.path for r in router.routes]
assert any('stream' in str(r) for r in routes), f'FAIL: SSE route not found: {routes}'
print('✅ SSE endpoint created')
"
```

---

### Task 4.2 — Wire Frontend to SSE Instead of Polling

**Committee finding**: H-4 (continuation)
**What**: Replace the `setInterval(fetchAlarms, 10000)` polling loop in `page.tsx` with an `EventSource` connection to the SSE endpoint.

**File to modify**: `frontend/app/page.tsx`

**Step 1** — Find and remove the polling interval (around line 100):
```tsx
const interval = setInterval(fetchAlarms, 10000)
```

**Step 2** — Replace with an SSE connection in the same `useEffect`:
```tsx
useEffect(() => {
  if (!token) return;

  // Initial fetch
  fetchAlarms();

  // SSE for real-time updates (replaces polling)
  const eventSource = new EventSource(
    `${process.env.NEXT_PUBLIC_API_BASE_URL}/api/v1/stream/alarms`,
    { withCredentials: false }
  );

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.event === 'alarms_updated') {
        fetchAlarms();  // Fetch fresh data when notified of changes
      }
    } catch (e) {
      console.error('SSE parse error:', e);
    }
  };

  eventSource.onerror = (err) => {
    console.warn('SSE connection error, falling back to 30s polling:', err);
    eventSource.close();
    // Graceful degradation: fall back to slower polling if SSE fails
    const fallback = setInterval(fetchAlarms, 30000);
    return () => clearInterval(fallback);
  };

  return () => eventSource.close();
}, [token]);
```

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
with open('frontend/app/page.tsx') as f: src = f.read()
assert 'EventSource' in src, 'FAIL: EventSource not added'
assert 'setInterval(fetchAlarms, 10000)' not in src, 'FAIL: 10s polling still present'
print('✅ Frontend uses SSE instead of polling')
"
```

---

## Layer 5 — Frontend Decomposition (2 weeks, after Layer 2, parallel with Layers 3-4)

---

### Task 5.1 — Wire Frontend KPIs to Real API

**Committee finding**: H-1
**What**: Dashboard header shows hardcoded `MTTR: 14m` and `Uptime: 99.98%`. Wire to real `/api/v1/autonomous/scorecard` endpoint.

**File to modify**: `frontend/app/page.tsx`

**Step 1** — Add state for scorecard data (near other `useState` declarations):
```tsx
const [scorecard, setScorecard] = useState<{avg_mttr: number | null, uptime_pct: number | null} | null>(null);
```

**Step 2** — Add fetch function:
```tsx
const fetchScorecard = async () => {
  if (!token) return;
  try {
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/api/v1/autonomous/scorecard`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (res.ok) {
      const data = await res.json();
      setScorecard({ avg_mttr: data.avg_mttr_minutes, uptime_pct: data.uptime_pct });
    }
  } catch (e) { console.error('Scorecard fetch failed:', e); }
};
```

**Step 3** — Call `fetchScorecard()` in the main `useEffect` alongside `fetchAlarms()`.

**Step 4** — Replace hardcoded stat cards (around lines 328–329):
```tsx
<StatCard icon={<Clock />} label="MTTR" value="14m" />
<StatCard icon={<CheckCircle />} label="Uptime" value="99.98%" />
```
With:
```tsx
<StatCard icon={<Clock />} label="MTTR"
  value={scorecard?.avg_mttr != null ? `${Math.round(scorecard.avg_mttr)}m` : "—"} />
<StatCard icon={<CheckCircle />} label="Uptime"
  value={scorecard?.uptime_pct != null ? `${scorecard.uptime_pct.toFixed(2)}%` : "—"} />
```

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
with open('frontend/app/page.tsx') as f: src = f.read()
assert 'fetchScorecard' in src, 'FAIL: scorecard fetch not added'
assert 'value=\"14m\"' not in src, 'FAIL: hardcoded MTTR still present'
assert 'value=\"99.98%\"' not in src, 'FAIL: hardcoded uptime still present'
print('✅ Frontend KPIs wired to real API')
"
```

---

### Task 5.2 — Decompose Frontend Monolith: Extract Components

**Committee finding**: M-1 (CTO §2.3 concern)
**What**: `page.tsx` is 564 lines with all components inline. Extract the most reusable components into separate files.

**Files to create**:
- `frontend/app/components/StatCard.tsx`
- `frontend/app/components/AlarmCard.tsx`
- `frontend/app/components/SitrepPanel.tsx`

**For each component**: cut the component definition from `page.tsx` and paste into the new file with proper `export default`. Add `import` statement back in `page.tsx`.

**`frontend/app/components/StatCard.tsx`**:
```tsx
interface StatCardProps {
  icon: React.ReactNode;
  label: string;
  value: string;
}
export default function StatCard({ icon, label, value }: StatCardProps) {
  // Paste the existing StatCard JSX here
}
```

**`frontend/app/components/AlarmCard.tsx`**:
```tsx
// Extract the alarm card rendering logic
// Accept alarm object as prop
```

**`frontend/app/components/SitrepPanel.tsx`**:
```tsx
// Extract the SITREP panel
// Add the AI Generated badge (from Task 3.3)
// Accept sitrep text and ai_generated flag as props
```

**In `page.tsx`**, add imports:
```tsx
import StatCard from './components/StatCard';
import AlarmCard from './components/AlarmCard';
import SitrepPanel from './components/SitrepPanel';
```

**Verification**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -c "
import os
assert os.path.exists('frontend/app/components/StatCard.tsx'), 'FAIL: StatCard not extracted'
assert os.path.exists('frontend/app/components/AlarmCard.tsx'), 'FAIL: AlarmCard not extracted'
assert os.path.exists('frontend/app/components/SitrepPanel.tsx'), 'FAIL: SitrepPanel not extracted'
with open('frontend/app/page.tsx') as f: src = f.read()
assert 'import StatCard' in src, 'FAIL: StatCard not imported in page.tsx'
print('✅ Frontend components extracted')
"
```

---


## Layer 6 — Governance Documents (parallel with Layers 3-5, after Layer 0)

These tasks create standalone Markdown documents. They do not touch any code files and can be executed by any agent in any order.

---

### Task 6.1 — NOC Operational Runbook

**Committee finding**: Amendment #5 (not started)
**File to create**: `docs/noc_runbook.md`

**Required sections**:
1. **Pedkai-Assisted Alarm Triage Workflow** — step-by-step: alarm arrives → Pedkai correlates → operator reviews clusters → operator decides action → Pedkai records decision
2. **Incident Lifecycle with Human Gates** — flowchart of the 3 mandatory gates: Gate 1 (SITREP approval by Shift Lead), Gate 2 (Action approval by Shift Lead), Gate 3 (Closure by Engineer or above). Include who is responsible at each gate and what scope is required.
3. **Escalation Matrix** — table with columns: Severity | Who is Notified | Response SLA | Pedkai Action. Rows: P1 (15 min, NOC Manager + On-call Engineer), P2 (1 hour, Shift Lead), P3 (4 hours, Engineer), P4 (Next business day, Engineer)
4. **Degraded-Mode Procedures** — what to do when Pedkai backend is unavailable: manual alarm triage using existing OSS tools, no dependency on Pedkai for incident tracking, fallback escalation contacts
5. **Emergency Service Protocol** — unconditional P1 for any entity with `entity_type = EMERGENCY_SERVICE`. Cannot be overridden by any policy or operator action.

**Verification**: File exists and contains all 5 section headings.
```bash
python -c "
with open('docs/noc_runbook.md') as f: src = f.read()
for section in ['Triage', 'Human Gate', 'Escalation', 'Degraded', 'Emergency']:
    assert section in src, f'FAIL: section {section} missing'
print('✅ NOC runbook complete')
"
```

---

### Task 6.2 — NOC Training Curriculum

**Committee finding**: Amendment #18 (not started)
**File to create**: `docs/training_curriculum.md`

**Required modules**:
- **Module 1: Reading Pedkai Reasoning Chains** (2 hours) — how to interpret confidence scores, what `[LOW CONFIDENCE — TEMPLATE FALLBACK]` means, when to override AI recommendations
- **Module 2: Operating Human Gates** (1 hour) — how to approve/reject SITREPs, how to approve/reject action recommendations, what happens if you reject
- **Module 3: Providing Feedback to Improve AI** (1 hour) — how to flag incorrect correlations, how to mark false positives, how the RLHF loop uses this feedback
- **Module 4: Degraded-Mode Operations** (2 hours) — full NOC workflow without Pedkai, manual alarm triage, escalation contacts

---

### Task 6.3 — DPIA Scoping Document

**Committee finding**: Amendment #4 (not started)
**File to create**: `docs/dpia_scope.md`

**Required content**:
- **Data categories processed**: Network KPIs, alarm events, customer identifiers, billing amounts, location data (cell site), LLM prompts (post-scrubbing)
- **Lawful basis**: Legitimate interests (network operations), contractual necessity (SLA management), legal obligation (emergency services)
- **Retention policies**: KPI data: 30 days rolling | Decision memory: indefinite (with right-to-erasure pathway) | Incidents: 7 years (regulatory) | LLM prompts (scrubbed): 90 days | Audit trails: 7 years
- **Right-to-erasure pathway**: Customer data can be anonymised in `customers` table; decision memory references customer IDs (not names) — erasure procedure documented
- **EU AI Act risk categorisation**: Pedkai is a "high-risk AI system" under Annex III (critical infrastructure). Required: conformity assessment, technical documentation, human oversight, accuracy metrics.
- **PII scrubbing confirmation**: All data sent to external LLMs is scrubbed per `pii_scrubber.py`. Scrub manifest retained for 90 days.

---

### Task 6.4 — Shadow-Mode Architecture Document

**Committee finding**: Amendment #17 (not started)
**File to create**: `docs/shadow_mode.md`

**Required content**:
- **What shadow mode is**: Pedkai runs alongside existing NOC, consuming the same alarm feed, generating recommendations that are logged but NOT shown to operators
- **Why it's needed**: Establishes the non-Pedkai baseline required for counterfactual metrics (scorecard). Without this, the scorecard returns `null` (as fixed in Task 2.1).
- **Duration**: 30-day shadow period → 90-day accuracy report → L2 decision on whether to enable advisory mode
- **Technical architecture**: Separate `shadow_mode: true` flag in config. When enabled, all recommendations go to `shadow_decisions` table, not to the incident workflow.
- **Success criteria**: False positive rate < 5%, missed correlation rate < 10%, MTTR improvement > 15% vs baseline

---

### Task 6.5 — Value Methodology Document

**Committee finding**: Amendment #20 (not started — CFO requirement)
**File to create**: `docs/value_methodology.md`

**Required content**:
- **Revenue protected**: Calculated as `sum(monthly_fee / 30 / 24 * estimated_outage_hours_prevented)` per customer. Only for `priced` customers (not `unpriced`). Confidence interval based on TTR estimation accuracy.
- **Incidents prevented**: Counted as drift detections that resulted in a recommendation that was approved AND where the KPI recovered within 2x the historical TTR. NOT counted if the KPI would have recovered without intervention (requires control group from shadow mode).
- **MTTR improvement**: `(baseline_mttr - pedkai_mttr) / baseline_mttr * 100%`. Baseline from shadow-mode period.
- **Board-presentable format**: All metrics include: measured value, confidence interval, methodology reference, data collection period, and a "pending" flag if shadow-mode baseline not yet collected.

---

### Task 6.6 — Data Architecture ADR

**Committee finding**: Amendment #9 (topology refresh strategy — partial)
**File to create**: `docs/data_architecture_adr.md`

**Required content**:
- **Decision**: PostgreSQL (primary) + TimescaleDB (KPI metrics) + SQLite (tests only)
- **Topology refresh strategy**: Topology data is synced from OSS via Kafka topic `topology.updates`. Each sync updates `last_synced_at` on `topology_relationships`. Staleness threshold: 7 days (configurable). Stale topology triggers an alert to the NOC.
- **Backup strategy**: Daily `pg_dump` to encrypted S3. Streaming replication to standby. RPO: 1 hour. RTO: 4 hours.
- **Graph scalability**: Current PostgreSQL recursive CTE approach supports up to ~10,000 entities. For larger networks, migration path to Neo4j or Apache AGE documented.

---

## Layer 7 — Mandatory Amendments (before pilot, after Layers 3-6)

These address the 16 unstarted mandatory amendments from the committee's original 26-item list.

---

### Task 7.1 — AI Maturity Ladder Definition

**Committee finding**: Amendment #15 (not started)
**File to create**: `docs/ai_maturity_ladder.md`
**File to modify**: `backend/app/core/config.py`

**Ladder levels**:
- **Level 1 — Assisted**: AI correlates alarms, human decides everything. No AI recommendations shown. (Current state during shadow mode)
- **Level 2 — Supervised**: AI shows recommendations with confidence scores. Human approves every action. (Current production target)
- **Level 3 — Autonomous** (future, not in v1): AI executes low-risk actions automatically. Human reviews post-hoc. Requires: 6 months Level 2 operation, false positive rate < 2%, explicit board approval.

Add to `config.py`:
```python
ai_maturity_level: int = 2  # 1=Assisted, 2=Supervised, 3=Autonomous (not available in v1)
```

Add enforcement in `autonomous_shield.py`: if `settings.ai_maturity_level < 3`, any call to an execution method raises `NotImplementedError("Autonomous execution requires AI maturity level 3")`.

---

### Task 7.2 — Drift Detection Calibration Protocol

**Committee finding**: Amendment #24 (not started)
**What**: The 15% KPI drift threshold in `autonomous_shield.py` is hardcoded and not configurable. Add configuration and false-positive rate tracking.

**File to modify**: `backend/app/core/config.py` — add:
```python
drift_threshold_pct: float = 15.0  # Configurable via DRIFT_THRESHOLD_PCT env var
drift_false_positive_window_days: int = 30  # Track FP rate over this window
```

**File to modify**: `backend/app/services/autonomous_shield.py` — replace hardcoded `0.15` with `settings.drift_threshold_pct / 100`.

**File to create**: `backend/app/services/drift_calibration.py` — a service that:
1. Counts drift detections in the last N days
2. Counts how many resulted in approved recommendations (true positives)
3. Counts how many were dismissed (false positives)
4. Returns `false_positive_rate` and recommends threshold adjustment if FP rate > 20%

---

### Task 7.3 — Customer Prioritisation Algorithm (Configurable)

**Committee finding**: Amendment #21 (not started)
**What**: Customer prioritisation is fixed revenue-based ordering. Make it configurable.

**File to create**: `backend/app/services/customer_prioritisation.py`

```python
"""
Configurable customer prioritisation for incident impact assessment.
Supports: revenue (default), SLA tier, churn risk, emergency service status.
"""
from enum import Enum
from typing import List

class PrioritisationStrategy(str, Enum):
    REVENUE = "revenue"
    SLA_TIER = "sla_tier"
    CHURN_RISK = "churn_risk"
    EMERGENCY_FIRST = "emergency_first"

def prioritise_customers(customers: List[dict], strategy: PrioritisationStrategy) -> List[dict]:
    if strategy == PrioritisationStrategy.REVENUE:
        return sorted(customers, key=lambda c: c.get("monthly_fee", 0), reverse=True)
    elif strategy == PrioritisationStrategy.SLA_TIER:
        tier_order = {"platinum": 0, "gold": 1, "silver": 2, "bronze": 3}
        return sorted(customers, key=lambda c: tier_order.get(c.get("sla_tier", "bronze"), 99))
    elif strategy == PrioritisationStrategy.CHURN_RISK:
        return sorted(customers, key=lambda c: c.get("churn_risk_score", 0), reverse=True)
    elif strategy == PrioritisationStrategy.EMERGENCY_FIRST:
        return sorted(customers, key=lambda c: (0 if c.get("is_emergency_service") else 1, -c.get("monthly_fee", 0)))
    return customers
```

Add `customer_prioritisation_strategy: str = "revenue"` to `config.py`.

---

### Task 7.4 — Data Retention Policies

**Committee finding**: Amendment #26 (not started)
**What**: No TTL, no archival, no cleanup jobs. Add a scheduled cleanup service.

**File to create**: `backend/app/services/data_retention.py`

```python
"""
Data retention enforcement service.
Retention policies per DPIA (docs/dpia_scope.md):
- KPI data: 30 days
- LLM prompts (scrubbed): 90 days
- Decision memory: indefinite (right-to-erasure via anonymisation)
- Incidents: 7 years
- Audit trails: 7 years
"""
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

RETENTION_POLICIES = {
    "kpi_metrics": timedelta(days=30),
    "llm_prompt_logs": timedelta(days=90),
    # incidents and audit_trails: 7 years — NOT auto-deleted, archived only
}

async def run_retention_cleanup(db: AsyncSession) -> dict:
    """Delete records older than their retention policy. Safe to run daily."""
    results = {}
    now = datetime.now(timezone.utc)
    for table, max_age in RETENTION_POLICIES.items():
        cutoff = now - max_age
        try:
            result = await db.execute(
                text(f"DELETE FROM {table} WHERE created_at < :cutoff"),
                {"cutoff": cutoff}
            )
            await db.commit()
            results[table] = {"deleted": result.rowcount, "cutoff": cutoff.isoformat()}
            logger.info(f"Retention cleanup: deleted {result.rowcount} rows from {table}")
        except Exception as e:
            logger.error(f"Retention cleanup failed for {table}: {e}")
            results[table] = {"error": str(e)}
    return results
```

Register as a FastAPI startup background task in `main.py` (run daily via `asyncio.create_task`).

---

### Task 7.5 — Per-Incident LLM Cost Tracking

**Committee finding**: Amendment #20 (not started)
**What**: No cost tracking. Sampling rate exists but cost is not measured per incident.

**File to modify**: `backend/app/services/llm_service.py`

After each LLM call, estimate and log the cost:
```python
def _estimate_cost(self, prompt: str, response_text: str) -> dict:
    """Estimate Gemini API cost. Gemini Flash: $0.075/1M input tokens, $0.30/1M output tokens."""
    # Rough token estimate: 4 chars per token
    input_tokens = len(prompt) // 4
    output_tokens = len(response_text) // 4
    input_cost = (input_tokens / 1_000_000) * 0.075
    output_cost = (output_tokens / 1_000_000) * 0.30
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(input_cost + output_cost, 6),
        "model": self._adapter.config.model_name if hasattr(self._adapter, 'config') else "unknown",
    }
```

Log cost per call and add `llm_cost_usd` column to `IncidentORM` to track cost per incident.

---

## Layer 8 — Verification & Load Tests (before pilot, after all other layers)

---

### Task 8.1 — Security Regression Test Suite

**File to create**: `tests/security/test_security_regressions.py`

**Test cases** (one per committee finding):
1. `test_pii_not_in_llm_prompt` — mock LLM adapter, verify no phone numbers/IMSI in prompt
2. `test_audit_trail_tenant_isolation` — Tenant A cannot read Tenant B's audit trail
3. `test_service_impact_tenant_isolation` — Tenant A cannot read Tenant B's clusters
4. `test_no_fabricated_scorecard_baselines` — scorecard returns `null` for non-Pedkai metrics
5. `test_emergency_service_uses_entity_type` — P1 triggered by `entity_type`, not string match
6. `test_proactive_comms_defaults_to_no_consent` — `check_consent()` returns `False` when field missing
7. `test_ai_watermark_in_sitrep_response` — SITREP response includes `ai_generated: true`
8. `test_mock_users_db_removed` — `MOCK_USERS_DB` not importable from `auth.py`

**Run command**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -m pytest tests/security/test_security_regressions.py -v
```

---

### Task 8.2 — Load Test at 200K Alarms/Day

**Committee finding**: Amendment #14 (partial — Locust file exists, no results documented)
**File to modify**: `tests/load/locustfile.py` — verify it covers alarm ingestion, cluster query, and SSE connection
**File to create**: `tests/load/LOAD_TEST_RESULTS.md` — document results after running

**Run command**:
```bash
cd /Users/himanshu/Projects/Pedkai
# 200K alarms/day = ~2.3 alarms/second
locust -f tests/load/locustfile.py --headless -u 50 -r 5 --run-time 5m \
  --host http://localhost:8000 \
  --html tests/load/results_$(date +%Y%m%d).html
```

**Success criteria**: p95 response time < 500ms for alarm queries, p99 < 2s, error rate < 0.1%.

---

### Task 8.3 — Multi-Tenant Isolation Regression Test

**File to create**: `tests/security/test_tenant_isolation_regression.py`

**Test cases**:
1. `test_topology_isolation` — Tenant A entities not visible to Tenant B
2. `test_incident_isolation` — Tenant A incidents not visible to Tenant B
3. `test_audit_trail_isolation` — Tenant A audit trail not visible to Tenant B (was H-5)
4. `test_service_impact_isolation` — Tenant A clusters not visible to Tenant B (was H-9)
5. `test_decision_trace_isolation` — Tenant A decisions not visible to Tenant B

**Run command**:
```bash
cd /Users/himanshu/Projects/Pedkai
python -m pytest tests/security/test_tenant_isolation_regression.py -v
```

---

## Amendment Status Tracker

| # | Amendment | Layer | Task | Status |
|---|-----------|-------|------|--------|
| 1 | Remove `execute_preventive_action()` | — | — | ✅ Already done |
| 2 | 3 human gates in incident lifecycle | — | — | ✅ Already done |
| 3 | LLM data classification + PII scrubbing | 0 | 0.2 | 🔲 Task 0.2 |
| 4 | DPIA and regulatory framework | 6 | 6.3 | 🔲 Task 6.3 |
| 5 | NOC operational runbook | 6 | 6.1 | 🔲 Task 6.1 |
| 6 | Emergency service unconditional P1 | 1 | 1.3 | 🔲 Task 1.3 |
| 7 | Audit trail (approver + model version + timestamps) | 3 | 3.4 | 🔲 Task 3.4 |
| 8 | LLM grounding validation + confidence scoring | 3 | 3.2 | �� Task 3.2 |
| 9 | Topology accuracy monitoring + refresh strategy | 2 | 2.4 | 🔲 Task 2.4 |
| 10 | BSS adapter abstraction layer | — | — | ✅ Already done |
| 11 | ARPU fallback → "unpriced" flag | — | — | ✅ Already done |
| 12 | Multi-tenant isolation testing | 0+8 | 0.3, 0.4, 8.3 | 🔲 Tasks 0.3, 0.4, 8.3 |
| 13 | WebSocket/SSE for real-time push | 4 | 4.1, 4.2 | 🔲 Tasks 4.1, 4.2 |
| 14 | Load test at 200K alarms/day | 8 | 8.2 | 🔲 Task 8.2 |
| 15 | AI maturity ladder | 7 | 7.1 | 🔲 Task 7.1 |
| 16 | TMF mapping for new APIs (621, 656, 921) | — | — | ⚠️ Out of scope for v1 — document as future work |
| 17 | Shadow-mode pilot architecture | 6 | 6.4 | 🔲 Task 6.4 |
| 18 | NOC training curriculum | 6 | 6.2 | 🔲 Task 6.2 |
| 19 | Demo milestones per work stream | — | — | ⚠️ Requires product owner input — not a code task |
| 20 | Per-incident LLM cost model | 7 | 7.5 | 🔲 Task 7.5 |
| 21 | Customer prioritisation algorithm (configurable) | 7 | 7.3 | 🔲 Task 7.3 |
| 22 | RBAC granularity for new endpoints | 1 | 1.1 | 🔲 Task 1.1 (adds shift_lead + engineer users) |
| 23 | Bias drift detection in RLHF loop | — | — | ⚠️ Requires RLHF loop to exist first — future work |
| 24 | Drift detection calibration protocol | 7 | 7.2 | 🔲 Task 7.2 |
| 25 | Dashboard progressive disclosure design | 5 | 5.2 | 🔲 Task 5.2 |
| 26 | Data retention policies | 7 | 7.4 | 🔲 Task 7.4 |

**Summary**: 4 done ✅ | 3 out-of-scope/future ⚠️ | 19 addressed by tasks in this plan 🔲

---

## Task Count Summary

| Layer | Tasks | Parallelisable | Estimated Effort |
|-------|-------|---------------|-----------------|
| Layer 0 — Emergency Hotfixes | 6 | Within layer | 48 hours |
| Layer 1 — Security Hardening | 5 | Within layer | 1 week |
| Layer 2 — Data Integrity | 4 | Within layer | 1 week |
| Layer 3 — LLM Pipeline | 4 | Within layer | 2 weeks |
| Layer 4 — Real-time Push | 2 | Within layer | 2 weeks |
| Layer 5 — Frontend | 2 | Within layer | 2 weeks |
| Layer 6 — Governance Docs | 6 | Fully parallel | 2 weeks |
| Layer 7 — Mandatory Amendments | 5 | Within layer | 2 weeks |
| Layer 8 — Verification | 3 | Within layer | 1 week |
| **Total** | **37** | | **~6 weeks** |

---

*Generated 18 February 2026 from `committee_reassessment_feb2026.md` (direct code audit, 18 Feb 2026)*  
*Supersedes `agentic_development_plan.md` (17 Feb 2026)*

