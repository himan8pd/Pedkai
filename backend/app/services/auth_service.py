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
