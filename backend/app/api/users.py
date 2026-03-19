"""
User management API for Pedkai.

Endpoints (all under /api/v1/users):

  GET    /users                        — list users in the current tenant
  POST   /users                        — create user + grant tenant access
  PATCH  /users/{user_id}/role         — change per-tenant role
  DELETE /users/{user_id}/access       — revoke access to current tenant
  POST   /users/{user_id}/reset-password — reset password
  PATCH  /users/{user_id}/deactivate   — platform-wide deactivate (admin:all)
  PATCH  /users/{user_id}/activate     — platform-wide activate   (admin:all)

Authorization:
  - ``users:manage`` scope required for all endpoints except deactivate/activate.
  - ``admin:all`` scope required for deactivate/activate.
  - tenant_admin can only assign TENANT_ADMIN_ASSIGNABLE_ROLES.
  - Admin can assign any role in ALL_ASSIGNABLE_ROLES.
  - All write operations are automatically scoped to current_user.tenant_id
    from the JWT, so a tenant_admin cannot act outside their own tenant.
"""

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Security, status
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.security import USERS_MANAGE, Role, User, get_current_user
from backend.app.services import auth_service

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class UserInTenantResponse(BaseModel):
    user_id: str
    username: str
    tenant_role: str
    is_active: bool
    granted_at: Optional[str]
    granted_by: Optional[str]


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str

    @field_validator("username")
    @classmethod
    def username_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("username must not be empty")
        return v

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


class UpdateRoleRequest(BaseModel):
    role: str


class ResetPasswordRequest(BaseModel):
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_tenant(current_user: User) -> str:
    """Extract tenant_id from JWT; raise 401 if not present (pre-tenant-select token)."""
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No tenant selected. Please call /auth/select-tenant first.",
        )
    return current_user.tenant_id


def _validate_assignable_role(role: str, assigner_role: str) -> None:
    """
    Raise 422 if *role* is not assignable by *assigner_role*.
    - admin        → may assign any role in ALL_ASSIGNABLE_ROLES
    - tenant_admin → may assign any role in TENANT_ADMIN_ASSIGNABLE_ROLES
    """
    if assigner_role == Role.ADMIN:
        allowed = auth_service.ALL_ASSIGNABLE_ROLES
    else:
        allowed = auth_service.TENANT_ADMIN_ASSIGNABLE_ROLES

    if role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Role '{role}' cannot be assigned by a '{assigner_role}'. "
                f"Allowed: {sorted(allowed)}"
            ),
        )


# ---------------------------------------------------------------------------
# GET /users — list users in the current tenant
# ---------------------------------------------------------------------------


@router.get("", response_model=List[UserInTenantResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[USERS_MANAGE]),
) -> Any:
    """Return all users that have access to the current tenant."""
    tenant_id = _require_tenant(current_user)
    rows = await auth_service.list_tenant_users(db, tenant_id)
    return [UserInTenantResponse(**r) for r in rows]


# ---------------------------------------------------------------------------
# POST /users — create user + grant access to current tenant
# ---------------------------------------------------------------------------


@router.post("", response_model=UserInTenantResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[USERS_MANAGE]),
) -> Any:
    """
    Create a new user account and immediately grant them access to the
    current tenant with the specified role.
    """
    tenant_id = _require_tenant(current_user)
    _validate_assignable_role(body.role, current_user.role)

    try:
        user = await auth_service.create_user_for_tenant(
            db=db,
            username=body.username,
            password=body.password,
            tenant_role=body.role,
            tenant_id=tenant_id,
            granted_by_id=current_user.user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        )

    return UserInTenantResponse(
        user_id=user.id,
        username=user.username,
        tenant_role=body.role,
        is_active=user.is_active,
        granted_at=None,
        granted_by=current_user.user_id,
    )


# ---------------------------------------------------------------------------
# PATCH /users/{user_id}/role — update per-tenant role
# ---------------------------------------------------------------------------


@router.patch("/{user_id}/role", response_model=dict)
async def update_role(
    user_id: str,
    body: UpdateRoleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[USERS_MANAGE]),
) -> Any:
    """Update the per-tenant role for a user within the current tenant."""
    tenant_id = _require_tenant(current_user)
    _validate_assignable_role(body.role, current_user.role)

    # Privilege guard: a tenant_admin cannot modify a user whose effective
    # tenant role is at the same or higher privilege level.
    if current_user.role == Role.TENANT_ADMIN:
        target_role = await auth_service.get_user_effective_tenant_role(
            db, user_id, tenant_id
        )
        if target_role not in auth_service.TENANT_ADMIN_ASSIGNABLE_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Cannot modify a user with role '{target_role}'.",
            )

    updated = await auth_service.update_user_tenant_role(
        db, user_id, tenant_id, body.role
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User does not have access to this tenant.",
        )
    return {"status": "updated", "user_id": user_id, "tenant_role": body.role}


# ---------------------------------------------------------------------------
# DELETE /users/{user_id}/access — revoke access to current tenant
# ---------------------------------------------------------------------------


@router.delete("/{user_id}/access", response_model=dict)
async def revoke_access(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[USERS_MANAGE]),
) -> Any:
    """
    Remove a user's access to the current tenant.
    The user account is preserved; they simply cannot log into this tenant.
    """
    tenant_id = _require_tenant(current_user)

    # Prevent self-revocation.
    if user_id == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot revoke your own access.",
        )

    # Privilege guard: a tenant_admin cannot revoke a user whose effective
    # tenant role is at the same or higher privilege level.
    if current_user.role == Role.TENANT_ADMIN:
        target_role = await auth_service.get_user_effective_tenant_role(
            db, user_id, tenant_id
        )
        if target_role not in auth_service.TENANT_ADMIN_ASSIGNABLE_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Cannot revoke access for a user with role '{target_role}'.",
            )

    deleted = await auth_service.revoke_user_tenant_access(db, user_id, tenant_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User does not have access to this tenant.",
        )
    return {"status": "revoked", "user_id": user_id, "tenant_id": tenant_id}


# ---------------------------------------------------------------------------
# POST /users/{user_id}/reset-password — reset password
# ---------------------------------------------------------------------------


@router.post("/{user_id}/reset-password", response_model=dict)
async def reset_password(
    user_id: str,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[USERS_MANAGE]),
) -> Any:
    """Reset the password for a user within the current tenant."""
    tenant_id = _require_tenant(current_user)

    # Verify the target user actually has access to this tenant (security boundary).
    access_row = await auth_service.get_user_tenant_access_row(db, user_id, tenant_id)
    if access_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User does not have access to this tenant.",
        )

    # Cross-tenant password guard: password reset is global (affects all tenants).
    # A tenant_admin may only reset passwords for users exclusive to this tenant.
    # If the user has access to other tenants too, a platform admin must do it.
    if current_user.role != Role.ADMIN:
        tenant_count = await auth_service.count_user_tenant_access(db, user_id)
        if tenant_count > 1:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Cannot reset password for a user with access to multiple tenants. "
                    "Contact a platform admin."
                ),
            )

    updated = await auth_service.reset_user_password(db, user_id, body.new_password)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return {"status": "password_reset", "user_id": user_id}


# ---------------------------------------------------------------------------
# PATCH /users/{user_id}/deactivate — platform-wide deactivate (admin:all)
# PATCH /users/{user_id}/activate   — platform-wide activate   (admin:all)
# ---------------------------------------------------------------------------


@router.patch("/{user_id}/deactivate", response_model=dict)
async def deactivate_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=["admin:all"]),
) -> Any:
    """
    Disable a user platform-wide (across all tenants).
    Requires ``admin:all`` scope — only the platform admin.
    """
    if user_id == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate yourself.",
        )
    updated = await auth_service.set_user_active(db, user_id, active=False)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return {"status": "deactivated", "user_id": user_id}


@router.patch("/{user_id}/activate", response_model=dict)
async def activate_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=["admin:all"]),
) -> Any:
    """Reactivate a previously deactivated user. Requires ``admin:all`` scope."""
    updated = await auth_service.set_user_active(db, user_id, active=True)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return {"status": "activated", "user_id": user_id}
