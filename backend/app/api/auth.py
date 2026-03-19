"""
Authentication router for Pedkai.

Provides endpoints for:
- /token          — exchange credentials for a short-lived JWT (no tenant bound yet)
- /tenants        — list tenants the authenticated user may access
- /select-tenant  — bind a tenant to the session (issues a new tenant-scoped JWT)

Flow:
1. Client POSTs to /token with username+password → receives a JWT *without* tenant_id
   plus a list of authorized tenants.
2. If the user has exactly one tenant, the frontend can immediately call /select-tenant.
   If multiple, the frontend shows a dropdown first.
3. Client POSTs to /select-tenant with the chosen tenant_id → receives a *new* JWT
   that has tenant_id baked in.  All subsequent API calls use this token.
"""

from datetime import timedelta
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.core.security import (
    ROLE_SCOPES,
    Role,
    User,
    create_access_token,
    get_current_user,
)
from backend.app.services import auth_service

router = APIRouter()
settings = get_settings()


# ---------------------------------------------------------------------------
# Pydantic response/request schemas (kept local — only used by this router)
# ---------------------------------------------------------------------------


class TenantInfo(BaseModel):
    """Tenant descriptor returned to the frontend.

    ``id`` is the plain-string slug used everywhere as ``tenant_id``
    (e.g. ``"casinolimit"``).  ``display_name`` is the prettier label
    for the UI (e.g. ``"CasinoLimit"``); falls back to ``id`` when not set.
    """

    id: str
    display_name: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    scopes: List[str]
    tenants: List[TenantInfo]
    tenant_id: Optional[str] = None


class SelectTenantRequest(BaseModel):
    tenant_id: str


class SelectTenantResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: str
    tenant_name: str
    role: str
    scopes: List[str]


# ---------------------------------------------------------------------------
# POST /token — initial login (no tenant bound yet)
# ---------------------------------------------------------------------------


@router.post("/token", response_model=TokenResponse)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Standard OAuth2 /token endpoint to exchange credentials for a JWT.

    The returned JWT does **not** contain a ``tenant_id`` yet.  The client
    must call ``/select-tenant`` to obtain a tenant-scoped token before
    accessing any data endpoints.

    The response includes a ``tenants`` array so the frontend knows which
    tenants are available without a second round-trip.
    """
    user = await auth_service.authenticate_user(
        db, form_data.username, form_data.password
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Fetch authorized tenants for this user
    tenants = await auth_service.get_tenants_for_user(db, user.id, role=user.role)

    if not tenants:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No authorized tenants for this user. Contact your administrator.",
        )

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    tenant_infos = [TenantInfo(id=t.id, display_name=t.label) for t in tenants]

    # If exactly one tenant, auto-bind it into the token for convenience.
    # For non-admin users, resolve the per-tenant role override (same logic as
    # /select-tenant) so single-tenant users receive the correct scopes.
    auto_tenant_id: Optional[str] = None
    role = user.role

    if len(tenants) == 1:
        auto_tenant_id = tenants[0].id
        if user.role != Role.ADMIN:
            access_row = await auth_service.get_user_tenant_access_row(
                db, user.id, auto_tenant_id
            )
            role = access_row.role if access_row and access_row.role else user.role

    scopes = ROLE_SCOPES.get(role, [])

    access_token = create_access_token(
        data={
            "sub": user.username,
            "user_id": user.id,
            "role": role,
            "scopes": scopes,
            **({"tenant_id": auto_tenant_id} if auto_tenant_id else {}),
        },
        expires_delta=access_token_expires,
    )

    return TokenResponse(
        access_token=access_token,
        role=role,
        scopes=scopes,
        tenants=tenant_infos,
        tenant_id=auto_tenant_id,
    )


# ---------------------------------------------------------------------------
# GET /tenants — list tenants for the current user
# ---------------------------------------------------------------------------


@router.get("/tenants", response_model=List[TenantInfo])
async def list_user_tenants(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Return the tenants the logged-in user is authorized to access.

    This is useful if the frontend needs to re-fetch the list (e.g. after
    a new tenant is provisioned) without forcing a full re-login.
    """
    # We need the user's DB id — look it up by username
    user_orm = await auth_service.get_user_by_username(db, current_user.username)
    if not user_orm:
        raise HTTPException(status_code=404, detail="User not found")

    tenants = await auth_service.get_tenants_for_user(db, user_orm.id, role=user_orm.role)
    return [TenantInfo(id=t.id, display_name=t.label) for t in tenants]


# ---------------------------------------------------------------------------
# POST /select-tenant — bind a tenant to the session (issue new JWT)
# ---------------------------------------------------------------------------


@router.post("/select-tenant", response_model=SelectTenantResponse)
async def select_tenant(
    body: SelectTenantRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Bind a tenant to the current session by issuing a **new** JWT that
    includes ``tenant_id``.

    Security:
    - The backend validates that the user actually has access to the
      requested tenant via the ``user_tenant_access`` table.
    - Direct API manipulation to switch to an unauthorized tenant is
      rejected with HTTP 403.
    """
    # Resolve DB user record (we need the id for access-check)
    user_orm = await auth_service.get_user_by_username(db, current_user.username)
    if not user_orm:
        raise HTTPException(status_code=404, detail="User not found")

    # Validate that the user is allowed to access this tenant
    allowed = await auth_service.validate_user_tenant_access(
        db, user_orm.id, body.tenant_id, role=user_orm.role
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access this tenant.",
        )

    # Look up tenant record for the response label
    tenant = await auth_service.get_tenant_by_id(db, body.tenant_id)
    if not tenant or not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found or inactive.",
        )

    # Issue a new token with tenant_id baked in.
    # For non-admin users, use the per-tenant role from user_tenant_access if set.
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    if user_orm.role == Role.ADMIN:
        role = Role.ADMIN
    else:
        access_row = await auth_service.get_user_tenant_access_row(
            db, user_orm.id, body.tenant_id
        )
        role = (access_row.role if access_row and access_row.role else user_orm.role)
    scopes = ROLE_SCOPES.get(role, [])

    access_token = create_access_token(
        data={
            "sub": user_orm.username,
            "user_id": user_orm.id,
            "role": role,
            "scopes": scopes,
            "tenant_id": tenant.id,
        },
        expires_delta=access_token_expires,
    )

    return SelectTenantResponse(
        access_token=access_token,
        tenant_id=tenant.id,
        tenant_name=tenant.label,
        role=role,
        scopes=scopes,
    )
