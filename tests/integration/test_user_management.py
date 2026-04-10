"""
User management CRUD endpoint tests.

Tests the /api/v1/users/* routes using client_real_auth so
real JWT validation and scope enforcement apply.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.user_orm import UserORM
from backend.app.models.tenant_orm import TenantORM
from backend.app.models.user_tenant_access_orm import UserTenantAccessORM
from backend.app.services.auth_service import hash_password
from backend.app.core.security import create_access_token, ROLE_SCOPES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed(db: AsyncSession):
    """Standard env: 1 tenant, 1 admin user with full access."""
    db.add(TenantORM(id="mgmt_tenant", display_name="Mgmt", is_active=True))
    await db.flush()
    admin = UserORM(
        username="mgmt_admin",
        hashed_password=hash_password("MgmtAdmin99!"),
        role="admin",
        tenant_id="mgmt_tenant",
    )
    db.add(admin)
    await db.flush()
    db.add(UserTenantAccessORM(user_id=admin.id, tenant_id="mgmt_tenant", role="admin"))
    await db.commit()
    return admin


def _admin_token(user_id: str) -> str:
    return create_access_token({
        "sub": user_id,
        "username": "mgmt_admin",
        "role": "admin",
        "tenant_id": "mgmt_tenant",
        "scopes": ROLE_SCOPES["admin"],
    })


# ---------------------------------------------------------------------------
# GET /users — list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_users(client_real_auth: AsyncClient, db_session: AsyncSession):
    """Admin can list users in their tenant."""
    admin = await _seed(db_session)
    token = _admin_token(admin.id)
    resp = await client_real_auth.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list)
    assert any(u["username"] == "mgmt_admin" for u in data)


@pytest.mark.asyncio
async def test_list_users_unauthenticated(client_real_auth: AsyncClient, db_session: AsyncSession):
    """Unauthenticated request returns 401."""
    await _seed(db_session)
    resp = await client_real_auth.get("/api/v1/users")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /users — create
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_user(client_real_auth: AsyncClient, db_session: AsyncSession):
    """Admin can create a new user."""
    admin = await _seed(db_session)
    token = _admin_token(admin.id)
    resp = await client_real_auth.post(
        "/api/v1/users",
        json={"username": "new_operator", "password": "NewOper99!", "role": "operator"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["username"] == "new_operator"
    assert body["tenant_role"] == "operator"


@pytest.mark.asyncio
async def test_create_duplicate_user(client_real_auth: AsyncClient, db_session: AsyncSession):
    """Duplicate username returns 409."""
    admin = await _seed(db_session)
    token = _admin_token(admin.id)
    # Create first
    await client_real_auth.post(
        "/api/v1/users",
        json={"username": "dup_user", "password": "DupPass99!", "role": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # Create duplicate
    resp = await client_real_auth.post(
        "/api/v1/users",
        json={"username": "dup_user", "password": "DupPass99!", "role": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# PATCH /users/{id}/role — update role
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_user_role(client_real_auth: AsyncClient, db_session: AsyncSession):
    """Admin can update a user's per-tenant role."""
    admin = await _seed(db_session)
    token = _admin_token(admin.id)
    # Create a user
    create_resp = await client_real_auth.post(
        "/api/v1/users",
        json={"username": "role_target", "password": "RolePass99!", "role": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    user_id = create_resp.json()["user_id"]

    resp = await client_real_auth.patch(
        f"/api/v1/users/{user_id}/role",
        json={"role": "operator"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["tenant_role"] == "operator"


# ---------------------------------------------------------------------------
# DELETE /users/{id}/access — revoke
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revoke_access(client_real_auth: AsyncClient, db_session: AsyncSession):
    """Admin can revoke another user's access to the current tenant."""
    admin = await _seed(db_session)
    token = _admin_token(admin.id)
    create_resp = await client_real_auth.post(
        "/api/v1/users",
        json={"username": "revoke_target", "password": "RevPass99!", "role": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    user_id = create_resp.json()["user_id"]

    resp = await client_real_auth.delete(
        f"/api/v1/users/{user_id}/access",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "revoked"


@pytest.mark.asyncio
async def test_cannot_revoke_self(client_real_auth: AsyncClient, db_session: AsyncSession):
    """Admin cannot revoke their own access."""
    admin = await _seed(db_session)
    token = _admin_token(admin.id)
    resp = await client_real_auth.delete(
        f"/api/v1/users/{admin.id}/access",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /users/{id}/reset-password
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reset_password(client_real_auth: AsyncClient, db_session: AsyncSession):
    """Admin can reset another user's password."""
    admin = await _seed(db_session)
    token = _admin_token(admin.id)
    create_resp = await client_real_auth.post(
        "/api/v1/users",
        json={"username": "pw_target", "password": "PwPass99!", "role": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    user_id = create_resp.json()["user_id"]

    resp = await client_real_auth.post(
        f"/api/v1/users/{user_id}/reset-password",
        json={"new_password": "ResetNew99!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
