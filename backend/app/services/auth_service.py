import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import bcrypt
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.core.security import Role
from backend.app.models.tenant_orm import TenantORM
from backend.app.models.user_orm import UserORM
from backend.app.models.user_tenant_access_orm import UserTenantAccessORM

logger = get_logger(__name__)


def hash_password(plain: str) -> str:
    """Hash a password using direct bcrypt for Python 3.14 compatibility."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(plain.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against a hash using direct bcrypt."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False


async def get_user_by_username(
    db: AsyncSession, username: str, tenant_id: Optional[str] = None
) -> Optional[UserORM]:
    """Look up a user by username, optionally scoped to a tenant.

    When *tenant_id* is provided the lookup uses the composite unique
    ``(tenant_id, username)`` key.  When omitted, returns the first
    matching row — only safe for platform-admin lookups where the
    username is known to be unique in practice (e.g. ``pedkai_admin``).
    """
    if tenant_id:
        result = await db.execute(
            select(UserORM).where(
                UserORM.username == username,
                UserORM.tenant_id == tenant_id,
            )
        )
    else:
        result = await db.execute(
            select(UserORM).where(UserORM.username == username)
        )
    return result.scalar_one_or_none()


async def authenticate_user(
    db: AsyncSession,
    username: str,
    password: str,
    tenant_id: Optional[str] = None,
) -> Optional[UserORM]:
    """Authenticate a user by credentials.

    If *tenant_id* is supplied, the user is looked up by the composite
    ``(tenant_id, username)`` key.  If *tenant_id* is ``None`` (admin
    login), the lookup is by username alone — but authentication only
    succeeds if the matched user has the ``admin`` role.  This prevents
    non-admin users from logging in without specifying a tenant.
    """
    user = await get_user_by_username(db, username, tenant_id=tenant_id)
    if not user or not user.is_active:
        return None
    # When no tenant_id is provided, only platform admins may authenticate.
    if tenant_id is None and user.role != Role.ADMIN:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


# ---------------------------------------------------------------------------
# Tenant helpers
# ---------------------------------------------------------------------------

# NOTE: SEED_TENANTS is no longer used. Tenants are loaded via data import scripts
# (e.g., load_telco2_tenant.py). The seeding function now only creates the global
# pedkai_admin user and grants access to all existing tenants in the database.


async def get_tenants_for_user(
    db: AsyncSession, user_id: str, role: str = ""
) -> List[TenantORM]:
    """
    Return all *active* tenants that a user is authorized to access.

    Admins bypass the ``user_tenant_access`` join and see every active tenant,
    so newly loaded tenants are immediately visible without re-seeding access rows.
    All other roles are restricted to their explicit ``user_tenant_access`` mappings.
    """
    if role == Role.ADMIN:
        result = await db.execute(
            select(TenantORM)
            .where(TenantORM.is_active.is_(True))
            .order_by(TenantORM.id)
        )
        return list(result.scalars().all())

    result = await db.execute(
        select(TenantORM)
        .join(
            UserTenantAccessORM,
            UserTenantAccessORM.tenant_id == TenantORM.id,
        )
        .where(
            UserTenantAccessORM.user_id == user_id,
            TenantORM.is_active.is_(True),
        )
        .order_by(TenantORM.id)
    )
    return list(result.scalars().all())


async def validate_user_tenant_access(
    db: AsyncSession, user_id: str, tenant_id: str, role: str = ""
) -> bool:
    """
    Return ``True`` if the user has access to the given tenant and the tenant
    is still active.  Used by ``/auth/select-tenant`` to prevent tenant-ID
    tampering.

    Admins bypass the ``user_tenant_access`` check — they may select any
    active tenant.
    """
    if role == Role.ADMIN:
        result = await db.execute(
            select(TenantORM).where(
                TenantORM.id == tenant_id,
                TenantORM.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none() is not None

    result = await db.execute(
        select(UserTenantAccessORM)
        .join(TenantORM, TenantORM.id == UserTenantAccessORM.tenant_id)
        .where(
            UserTenantAccessORM.user_id == user_id,
            UserTenantAccessORM.tenant_id == tenant_id,
            TenantORM.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none() is not None


async def get_tenant_by_id(db: AsyncSession, tenant_id: str) -> Optional[TenantORM]:
    """Look up a tenant by its plain-string primary key."""
    result = await db.execute(select(TenantORM).where(TenantORM.id == tenant_id))
    return result.scalar_one_or_none()


async def get_user_tenant_access_row(
    db: AsyncSession, user_id: str, tenant_id: str
) -> Optional[UserTenantAccessORM]:
    """Return the specific user↔tenant access row, or None if it doesn't exist."""
    result = await db.execute(
        select(UserTenantAccessORM).where(
            UserTenantAccessORM.user_id == user_id,
            UserTenantAccessORM.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: str) -> Optional[UserORM]:
    """Look up a user by their UUID primary key."""
    result = await db.execute(select(UserORM).where(UserORM.id == user_id))
    return result.scalar_one_or_none()


async def get_user_effective_tenant_role(
    db: AsyncSession, user_id: str, tenant_id: str
) -> Optional[str]:
    """
    Return the effective role of a user within a specific tenant.

    Per-tenant override in ``user_tenant_access.role`` takes precedence;
    falls back to ``UserORM.role`` when no override is set.
    Returns ``None`` if the user has no access row for this tenant.
    """
    row = await get_user_tenant_access_row(db, user_id, tenant_id)
    if row is None:
        return None
    if row.role:
        return row.role
    user = await get_user_by_id(db, user_id)
    return user.role if user else None


async def count_user_tenant_access(db: AsyncSession, user_id: str) -> int:
    """Return the number of tenants the user has explicit access rows for."""
    result = await db.execute(
        select(UserTenantAccessORM).where(UserTenantAccessORM.user_id == user_id)
    )
    return len(result.scalars().all())


# ---------------------------------------------------------------------------
# User management (called by /api/v1/users endpoints)
# ---------------------------------------------------------------------------

# Roles that a tenant_admin is allowed to assign (cannot escalate to admin/tenant_admin).
TENANT_ADMIN_ASSIGNABLE_ROLES = {
    Role.OPERATOR,
    Role.SHIFT_LEAD,
    Role.ENGINEER,
    Role.VIEWER,
}

# All valid roles (including tenant_admin; admin can assign any of these).
ALL_ASSIGNABLE_ROLES = TENANT_ADMIN_ASSIGNABLE_ROLES | {Role.TENANT_ADMIN}


async def list_tenant_users(
    db: AsyncSession, tenant_id: str
) -> List[Dict[str, Any]]:
    """
    Return all users that have access to *tenant_id*, with their effective
    per-tenant role and basic profile data.
    """
    result = await db.execute(
        select(UserORM, UserTenantAccessORM)
        .join(UserTenantAccessORM, UserTenantAccessORM.user_id == UserORM.id)
        .where(UserTenantAccessORM.tenant_id == tenant_id)
        .order_by(UserORM.username)
    )
    rows = result.all()
    return [
        {
            "user_id": user.id,
            "username": user.username,
            # Per-tenant role if set; otherwise the user's global default role.
            "tenant_role": access.role or user.role,
            "is_active": user.is_active,
            "granted_at": access.granted_at.isoformat() if access.granted_at else None,
            "granted_by": access.granted_by,
        }
        for user, access in rows
    ]


async def create_user_for_tenant(
    db: AsyncSession,
    username: str,
    password: str,
    tenant_role: str,
    tenant_id: str,
    granted_by_id: str,
) -> UserORM:
    """
    Create a new user and immediately grant them access to *tenant_id* with
    *tenant_role*.  Raises ``ValueError`` if the username already exists
    within the specified tenant.
    """
    if await get_user_by_username(db, username, tenant_id=tenant_id):
        raise ValueError(f"Username '{username}' already exists in this tenant.")

    user = UserORM(
        username=username,
        hashed_password=hash_password(password),
        role=tenant_role,   # global default = the role they're being created with
        tenant_id=tenant_id,  # home tenant (part of composite unique with username)
        is_active=True,
    )
    db.add(user)
    await db.flush()   # populate user.id

    db.add(
        UserTenantAccessORM(
            user_id=user.id,
            tenant_id=tenant_id,
            role=tenant_role,
            granted_by=granted_by_id,
        )
    )
    await db.commit()
    await db.refresh(user)
    logger.info(
        f"Created user '{username}' for tenant '{tenant_id}' with role '{tenant_role}'"
        f" (granted by user_id={granted_by_id})"
    )
    return user


async def update_user_tenant_role(
    db: AsyncSession, user_id: str, tenant_id: str, new_role: str
) -> bool:
    """
    Update the per-tenant role for an existing user↔tenant mapping.
    Returns ``True`` on success, ``False`` if the access row doesn't exist.
    """
    row = await get_user_tenant_access_row(db, user_id, tenant_id)
    if row is None:
        return False
    row.role = new_role  # type: ignore[assignment]
    await db.commit()
    logger.info(f"Updated role for user {user_id} in tenant {tenant_id} → {new_role}")
    return True


async def revoke_user_tenant_access(
    db: AsyncSession, user_id: str, tenant_id: str
) -> bool:
    """
    Remove the user↔tenant access row.  The user still exists but can no
    longer log in to this tenant.  Returns ``True`` if a row was deleted.
    """
    result = await db.execute(
        delete(UserTenantAccessORM).where(
            UserTenantAccessORM.user_id == user_id,
            UserTenantAccessORM.tenant_id == tenant_id,
        )
    )
    await db.commit()
    deleted = result.rowcount > 0
    if deleted:
        logger.info(f"Revoked user {user_id} access to tenant {tenant_id}")
    return deleted


async def set_user_active(db: AsyncSession, user_id: str, *, active: bool) -> bool:
    """
    Activate or deactivate a user platform-wide (all tenants).
    Returns ``True`` if the user was found and updated.
    """
    user = await get_user_by_id(db, user_id)
    if user is None:
        return False
    user.is_active = active  # type: ignore[assignment]
    await db.commit()
    state = "activated" if active else "deactivated"
    logger.info(f"User {user_id} ({user.username}) {state}")
    return True


async def reset_user_password(
    db: AsyncSession, user_id: str, new_password: str
) -> bool:
    """
    Replace the user's password hash.
    Returns ``True`` if the user was found and updated.
    """
    user = await get_user_by_id(db, user_id)
    if user is None:
        return False
    user.hashed_password = hash_password(new_password)  # type: ignore[assignment]
    await db.commit()
    logger.info(f"Password reset for user {user_id} ({user.username})")
    return True





# ---------------------------------------------------------------------------
# Seeding (first-startup bootstrap)
# ---------------------------------------------------------------------------


async def seed_tenants(db: AsyncSession) -> dict[str, TenantORM]:
    """
    Ensure all known tenants exist in the ``tenants`` table.

    The tenant ``id`` is the same plain string that every data table
    already uses in its ``tenant_id`` column (e.g. ``"casinolimit"``).
    No UUIDs — the id *is* the human-readable slug.

    Returns a dict mapping tenant_id → ORM instance.
    Idempotent — re-running will not create duplicates.
    """
    tenant_map: dict[str, TenantORM] = {}

    for tenant_id, display_name in SEED_TENANTS.items():
        existing = await get_tenant_by_id(db, tenant_id)
        if existing:
            tenant_map[tenant_id] = existing
        else:
            tenant = TenantORM(id=tenant_id, display_name=display_name, is_active=True)
            db.add(tenant)
            await db.flush()
            tenant_map[tenant_id] = tenant
            logger.info(f"Seeded tenant '{tenant_id}' (display_name='{display_name}')")

    await db.commit()
    return tenant_map


async def seed_default_users(db: AsyncSession) -> None:
    """
    Seed the global pedkai_admin user on first startup.

    Data Model (aligned with current schema):
    - Only one global user: pedkai_admin (role=ADMIN)
    - All other users are tenant-scoped: <tenant_id>_admin, <tenant_id>_operator, etc.
    - Tenant users are created per-tenant, not globally
    - pedkai_admin has access to all existing tenants

    This function does NOT create tenants or tenant-local users.
    Tenants are loaded via data import scripts (e.g., load_telco2_tenant.py).
    Tenant-local users are created on-demand via the user management API.
    """
    # 1. Seed the global pedkai_admin user (idempotent).
    #    The no-tenant lookup is safe here because pedkai_admin is the only
    #    admin-role user and the name is reserved.
    admin_user = await get_user_by_username(db, "pedkai_admin")  # tenant_id=None → global lookup
    if not admin_user:
        # The legacy tenant_id column is NOT NULL, so we must supply a value.
        # Fetch the first active tenant from the DB rather than hardcoding one.
        first_tenant = await db.execute(
            select(TenantORM).where(TenantORM.is_active.is_(True)).limit(1)
        )
        first_tenant_id = (t := first_tenant.scalar_one_or_none()) and t.id
        if not first_tenant_id:
            logger.error(
                "Cannot seed pedkai_admin: no active tenants exist. "
                "Load tenant data first (e.g., load_telco2_tenant.py)."
            )
            return

        admin_user = UserORM(
            username="pedkai_admin",
            hashed_password=hash_password(
                os.getenv("PEDKAI_ADMIN_PASSWORD", "CHANGE_ME")
            ),
            role=Role.ADMIN,
            tenant_id=first_tenant_id,  # Legacy NOT NULL column; user_tenant_access is authoritative
            must_change_password=True,  # Force password change on first login
        )
        db.add(admin_user)
        await db.flush()
        logger.info(f"Seeded global user 'pedkai_admin' (legacy tenant_id='{first_tenant_id}')")

    await db.commit()

    # 2. Grant pedkai_admin access to all existing active tenants (idempotent)
    existing_tenants = await db.execute(
        select(TenantORM).where(TenantORM.is_active.is_(True))
    )
    tenants = list(existing_tenants.scalars().all())

    if tenants:
        # Ensure access rows exist for pedkai_admin to all tenants
        for tenant in tenants:
            exists = await db.execute(
                select(UserTenantAccessORM).where(
                    UserTenantAccessORM.user_id == admin_user.id,
                    UserTenantAccessORM.tenant_id == tenant.id,
                )
            )
            if not exists.scalar_one_or_none():
                db.add(
                    UserTenantAccessORM(
                        user_id=admin_user.id,
                        tenant_id=tenant.id,
                        role=Role.ADMIN,  # pedkai_admin is admin in every tenant
                    )
                )
        await db.commit()
        logger.info(
            f"Granted pedkai_admin access to {len(tenants)} existing tenant(s)"
        )
    else:
        logger.warning(
            "No active tenants found. pedkai_admin will not be able to log in until "
            "tenants are loaded into the database (e.g., via load_telco2_tenant.py)"
        )


async def _seed_user_tenant_access(
    db: AsyncSession,
    tenants: list[TenantORM],
) -> None:
    """
    Ensure every seeded user has ``user_tenant_access`` rows.

    Default policy (demo convenience):
    - Every user gets access to every seeded tenant.
    - In production you would restrict this per-user.

    Idempotent — checks for existing rows before inserting.
    """
    all_users_result = await db.execute(select(UserORM))
    all_users = list(all_users_result.scalars().all())

    for user in all_users:
        for tenant in tenants:
            exists = await db.execute(
                select(UserTenantAccessORM).where(
                    UserTenantAccessORM.user_id == user.id,
                    UserTenantAccessORM.tenant_id == tenant.id,
                )
            )
            if exists.scalar_one_or_none() is None:
                db.add(
                    UserTenantAccessORM(
                        user_id=user.id,
                        tenant_id=tenant.id,
                    )
                )
                logger.info(
                    f"Granted user '{user.username}' access to tenant '{tenant.id}'"
                )

    await db.commit()
