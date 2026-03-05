import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint

from backend.app.core.database import Base


class UserTenantAccessORM(Base):
    """
    ORM Model for User-to-Tenant authorization mapping.

    Maps which tenants each user is authorized to access.
    A user may have access to one or many tenants.
    At login time, the system queries this table to determine
    which tenants to offer the user.

    Rules:
    - If no rows exist for a user_id → deny access.
    - If exactly one row exists → auto-bind session to that tenant.
    - If multiple rows exist → show tenant selection dropdown.
    """

    __tablename__ = "user_tenant_access"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        String(100),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    granted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant"),)

    def __repr__(self):
        return f"<UserTenantAccess user={self.user_id} tenant={self.tenant_id}>"
