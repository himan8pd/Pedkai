import os
from typing import List, Optional

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
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


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[UserORM]:
    result = await db.execute(select(UserORM).where(UserORM.username == username))
    return result.scalar_one_or_none()


async def authenticate_user(
    db: AsyncSession, username: str, password: str
) -> Optional[UserORM]:
    user = await get_user_by_username(db, username)
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


# ---------------------------------------------------------------------------
# Tenant helpers
# ---------------------------------------------------------------------------

# The three known tenants and their display labels.
# tenant_id (plain string PK) → display_name shown in the UI.
# Adding a new tenant is just one row in the DB — no code change needed.
SEED_TENANTS: dict[str, str] = {
    "casinolimit": "CasinoLimit",
    "pedkai_synthetic_01": "Pedkai Synthetic 01",
    "pedkai_telco2_01": "Pedkai Telco2 01",
}


async def get_tenants_for_user(db: AsyncSession, user_id: str) -> List[TenantORM]:
    """
    Return all *active* tenants that a user is authorized to access,
    by joining the ``user_tenant_access`` mapping table.
    """
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
    db: AsyncSession, user_id: str, tenant_id: str
) -> bool:
    """
    Return ``True`` if the user has an explicit mapping to the given tenant
    *and* the tenant is still active.  Used by the ``/auth/select-tenant``
    endpoint to prevent tenant-ID tampering.
    """
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
    Seed 4 default users on first startup.  Passwords from env vars.

    After users are created (or already exist) this also calls
    ``_seed_user_tenant_access`` to ensure every user has at least one
    tenant mapping.
    """
    from backend.app.core.security import Role

    # 1. Ensure tenants exist first
    tenant_map = await seed_tenants(db)

    # The legacy ``user_orm.tenant_id`` column is kept for backward-compat
    # with code that reads ``user.tenant_id`` directly.  Going forward
    # the ``user_tenant_access`` table is authoritative.
    default_tenant_id = "casinolimit"

    # 2. Seed users (idempotent — skip if any user already exists)
    existing = await db.execute(select(UserORM).limit(1))
    users_exist = existing.scalar_one_or_none() is not None

    if not users_exist:
        users = [
            UserORM(
                username="admin",
                hashed_password=hash_password(os.getenv("ADMIN_PASSWORD", "CHANGE_ME")),
                role=Role.ADMIN,
                tenant_id=default_tenant_id,
            ),
            UserORM(
                username="operator",
                hashed_password=hash_password(
                    os.getenv("OPERATOR_PASSWORD", "CHANGE_ME")
                ),
                role=Role.OPERATOR,
                tenant_id=default_tenant_id,
            ),
            UserORM(
                username="shift_lead",
                hashed_password=hash_password(
                    os.getenv("SHIFT_LEAD_PASSWORD", "CHANGE_ME")
                ),
                role=Role.SHIFT_LEAD,
                tenant_id=default_tenant_id,
            ),
            UserORM(
                username="engineer",
                hashed_password=hash_password(
                    os.getenv("ENGINEER_PASSWORD", "CHANGE_ME")
                ),
                role=Role.ENGINEER,
                tenant_id=default_tenant_id,
            ),
        ]
        db.add_all(users)
        await db.commit()
        logger.info("Seeded 4 default users")

    # 3. Seed user↔tenant access mappings (always runs — idempotent)
    await _seed_user_tenant_access(db, list(tenant_map.values()))


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
