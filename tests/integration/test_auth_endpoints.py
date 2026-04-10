"""
Auth endpoint tests (QA-08/09/10).

Uses client_real_auth fixture so real JWT validation applies.
Seeds users and tenants directly into the test DB.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.user_orm import UserORM
from backend.app.models.tenant_orm import TenantORM
from backend.app.models.user_tenant_access_orm import UserTenantAccessORM
from backend.app.services.auth_service import hash_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_tenant(db: AsyncSession, tid: str, display: str = "") -> TenantORM:
    t = TenantORM(id=tid, display_name=display or tid, is_active=True)
    db.add(t)
    await db.flush()
    return t


async def _seed_user(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    role: str,
    tenant_id: str,
    is_active: bool = True,
    must_change_password: bool = False,
) -> UserORM:
    u = UserORM(
        username=username,
        hashed_password=hash_password(password),
        role=role,
        tenant_id=tenant_id,
        is_active=is_active,
        must_change_password=must_change_password,
    )
    db.add(u)
    await db.flush()
    return u


async def _grant_access(
    db: AsyncSession, user_id: str, tenant_id: str, role: str | None = None
) -> None:
    db.add(UserTenantAccessORM(user_id=user_id, tenant_id=tenant_id, role=role))
    await db.flush()


async def _setup_env(db: AsyncSession):
    """Create a standard test env: 2 tenants, 1 admin, 1 operator."""
    t1 = await _seed_tenant(db, "test_alpha", "Test Alpha")
    t2 = await _seed_tenant(db, "test_beta", "Test Beta")
    admin = await _seed_user(
        db, username="admin_user", password="AdminPass99!", role="admin", tenant_id="test_alpha"
    )
    await _grant_access(db, admin.id, "test_alpha", "admin")
    await _grant_access(db, admin.id, "test_beta", "admin")

    op = await _seed_user(
        db, username="op_user", password="OperPass99!", role="operator", tenant_id="test_alpha"
    )
    await _grant_access(db, op.id, "test_alpha", "operator")
    await db.commit()
    return t1, t2, admin, op


# ---------------------------------------------------------------------------
# POST /token  — login
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_success(client_real_auth: AsyncClient, db_session: AsyncSession):
    """Successful login returns JWT with tenant list."""
    await _setup_env(db_session)
    resp = await client_real_auth.post(
        "/api/v1/auth/token",
        data={"username": "admin_user", "password": "AdminPass99!"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 20
    assert body["role"] == "admin"
    assert isinstance(body["tenants"], list)
    assert len(body["tenants"]) >= 2


@pytest.mark.asyncio
async def test_login_bad_password(client_real_auth: AsyncClient, db_session: AsyncSession):
    """Wrong password returns 401."""
    await _setup_env(db_session)
    resp = await client_real_auth.post(
        "/api/v1/auth/token",
        data={"username": "admin_user", "password": "wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client_real_auth: AsyncClient, db_session: AsyncSession):
    """Unknown username returns 401."""
    await _setup_env(db_session)
    resp = await client_real_auth.post(
        "/api/v1/auth/token",
        data={"username": "ghost", "password": "whatever"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_inactive_user(client_real_auth: AsyncClient, db_session: AsyncSession):
    """Deactivated user cannot log in."""
    await _setup_env(db_session)
    await _seed_user(
        db_session, username="dead_user", password="DeadPass99!", role="viewer",
        tenant_id="test_alpha", is_active=False,
    )
    await db_session.commit()
    resp = await client_real_auth.post(
        "/api/v1/auth/token",
        data={"username": "dead_user", "password": "DeadPass99!"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /select-tenant
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_select_tenant_success(client_real_auth: AsyncClient, db_session: AsyncSession):
    """Select-tenant binds tenant and returns scoped JWT."""
    await _setup_env(db_session)
    # Login first
    login = await client_real_auth.post(
        "/api/v1/auth/token",
        data={"username": "admin_user", "password": "AdminPass99!"},
    )
    token = login.json()["access_token"]

    resp = await client_real_auth.post(
        "/api/v1/auth/select-tenant",
        json={"tenant_id": "test_beta"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tenant_id"] == "test_beta"
    assert body["tenant_name"] == "Test Beta"
    assert len(body["access_token"]) > 20


@pytest.mark.asyncio
async def test_select_tenant_unauthorized(client_real_auth: AsyncClient, db_session: AsyncSession):
    """Operator with access to only one tenant cannot select a different one."""
    await _setup_env(db_session)
    login = await client_real_auth.post(
        "/api/v1/auth/token",
        data={"username": "op_user", "password": "OperPass99!", "tenant_id": "test_alpha"},
    )
    token = login.json()["access_token"]

    resp = await client_real_auth.post(
        "/api/v1/auth/select-tenant",
        json={"tenant_id": "test_beta"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /refresh
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_token(client_real_auth: AsyncClient, db_session: AsyncSession):
    """Refresh returns a new valid JWT."""
    await _setup_env(db_session)
    login = await client_real_auth.post(
        "/api/v1/auth/token",
        data={"username": "admin_user", "password": "AdminPass99!"},
    )
    token = login.json()["access_token"]

    resp = await client_real_auth.post(
        "/api/v1/auth/refresh",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 20
    # Token may be identical if generated in the same second (same exp claim).
    # The important thing is that we got a valid response.


@pytest.mark.asyncio
async def test_refresh_without_token(client_real_auth: AsyncClient, db_session: AsyncSession):
    """Refresh without Authorization header returns 401."""
    await _setup_env(db_session)
    resp = await client_real_auth.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /tenants
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_tenants(client_real_auth: AsyncClient, db_session: AsyncSession):
    """Authenticated user can list their tenants."""
    await _setup_env(db_session)
    login = await client_real_auth.post(
        "/api/v1/auth/token",
        data={"username": "admin_user", "password": "AdminPass99!"},
    )
    token = login.json()["access_token"]

    resp = await client_real_auth.get(
        "/api/v1/auth/tenants",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    tenants = resp.json()
    assert isinstance(tenants, list)
    ids = [t["id"] for t in tenants]
    assert "test_alpha" in ids
    assert "test_beta" in ids


# ---------------------------------------------------------------------------
# POST /change-password
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_change_password_success(client_real_auth: AsyncClient, db_session: AsyncSession):
    """User can change their own password."""
    await _setup_env(db_session)
    login = await client_real_auth.post(
        "/api/v1/auth/token",
        data={"username": "admin_user", "password": "AdminPass99!"},
    )
    token = login.json()["access_token"]

    resp = await client_real_auth.post(
        "/api/v1/auth/change-password",
        json={"current_password": "AdminPass99!", "new_password": "NewAdminPass1!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text

    # Verify new password works
    login2 = await client_real_auth.post(
        "/api/v1/auth/token",
        data={"username": "admin_user", "password": "NewAdminPass1!"},
    )
    assert login2.status_code == 200


@pytest.mark.asyncio
async def test_change_password_wrong_current(client_real_auth: AsyncClient, db_session: AsyncSession):
    """Wrong current password is rejected."""
    await _setup_env(db_session)
    login = await client_real_auth.post(
        "/api/v1/auth/token",
        data={"username": "admin_user", "password": "AdminPass99!"},
    )
    token = login.json()["access_token"]

    resp = await client_real_auth.post(
        "/api/v1/auth/change-password",
        json={"current_password": "wrong", "new_password": "NewAdminPass1!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_change_password_too_short(client_real_auth: AsyncClient, db_session: AsyncSession):
    """New password under 8 chars is rejected."""
    await _setup_env(db_session)
    login = await client_real_auth.post(
        "/api/v1/auth/token",
        data={"username": "admin_user", "password": "AdminPass99!"},
    )
    token = login.json()["access_token"]

    resp = await client_real_auth.post(
        "/api/v1/auth/change-password",
        json={"current_password": "AdminPass99!", "new_password": "short"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
