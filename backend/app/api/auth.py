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

from fastapi import APIRouter, Depends, Form, HTTPException, status
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
    must_change_password: bool = False


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
    tenant_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    OAuth2 /token endpoint to exchange credentials for a JWT.

    Accepts an optional ``tenant_id`` form field to scope the login to a
    specific tenant.  When omitted, only platform-admin users (role=admin)
    may authenticate.

    The returned JWT does **not** contain a ``tenant_id`` yet (unless the
    user has exactly one authorized tenant).  The client must call
    ``/select-tenant`` to obtain a tenant-scoped token before accessing
    data endpoints.

    The response includes a ``tenants`` array so the frontend knows which
    tenants are available without a second round-trip.
    """
    user = await auth_service.authenticate_user(
        db, form_data.username, form_data.password, tenant_id=tenant_id
    )
    if not user:
        # Provide a helpful hint when tenant_id is missing for non-admin users.
        detail = "Incorrect username or password"
        if tenant_id is None:
            detail += ". Non-admin users must specify a tenant."
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
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
            "sub": user.id,
            "username": user.username,
            "user_id": user.id,
            "role": role,
            "scopes": scopes,
            **({"tenant_id": auto_tenant_id} if auto_tenant_id else {}),
        },
        expires_delta=access_token_expires,
    )

    # Check if user must change their password on first login
    must_change = getattr(user, "must_change_password", False)

    return TokenResponse(
        access_token=access_token,
        role=role,
        scopes=scopes,
        tenants=tenant_infos,
        tenant_id=auto_tenant_id,
        must_change_password=must_change,
    )


# ---------------------------------------------------------------------------
# POST /refresh — silently reissue a JWT before it expires
# ---------------------------------------------------------------------------


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Reissue a fresh JWT for the currently authenticated user.

    The client should call this periodically (e.g. every 20 minutes)
    to keep the session alive without forcing a re-login.  The new token
    preserves the same claims (role, scopes, tenant_id) as the original.
    """
    # Verify the user still exists and is active
    user_orm = await auth_service.get_user_by_id(db, current_user.user_id)
    if not user_orm or not user_orm.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or deleted.",
        )

    # Re-resolve the role/scopes (in case they changed since last login)
    role = user_orm.role
    if current_user.tenant_id and user_orm.role != Role.ADMIN:
        access_row = await auth_service.get_user_tenant_access_row(
            db, user_orm.id, current_user.tenant_id
        )
        role = access_row.role if access_row and access_row.role else user_orm.role

    scopes = ROLE_SCOPES.get(role, [])
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)

    access_token = create_access_token(
        data={
            "sub": user_orm.id,
            "username": user_orm.username,
            "user_id": user_orm.id,
            "role": role,
            "scopes": scopes,
            **({"tenant_id": current_user.tenant_id} if current_user.tenant_id else {}),
        },
        expires_delta=access_token_expires,
    )

    return RefreshResponse(access_token=access_token)


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
    # Resolve DB user by the UUID from the JWT
    user_orm = await auth_service.get_user_by_id(db, current_user.user_id)
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
    # Resolve DB user record by UUID from JWT
    user_orm = await auth_service.get_user_by_id(db, current_user.user_id)
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
            "sub": user_orm.id,
            "username": user_orm.username,
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


# ---------------------------------------------------------------------------
# POST /change-password — self-service password change
# ---------------------------------------------------------------------------


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ChangePasswordResponse(BaseModel):
    message: str


@router.post("/change-password", response_model=ChangePasswordResponse)
async def change_password(
    body: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Change the current user's password.

    Requires the current password for verification. On success, clears the
    ``must_change_password`` flag so the user is no longer prompted.

    Password requirements:
    - Minimum 8 characters
    - Must differ from current password
    """
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters.",
        )

    user_orm = await auth_service.get_user_by_id(db, current_user.user_id)
    if not user_orm:
        raise HTTPException(status_code=404, detail="User not found")

    # Verify current password
    if not auth_service.verify_password(body.current_password, user_orm.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect.",
        )

    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must differ from current password.",
        )

    # Update password and clear the forced-change flag
    user_orm.hashed_password = auth_service.hash_password(body.new_password)
    user_orm.must_change_password = False
    await db.commit()

    return ChangePasswordResponse(message="Password changed successfully.")
