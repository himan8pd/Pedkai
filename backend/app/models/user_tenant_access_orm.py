import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint

from backend.app.core.database import Base


class UserTenantAccessORM(Base):
    """
    ORM Model for User-to-Tenant authorization mapping.

    Maps which tenants each user is authorized to access, and what role they
    hold within that specific tenant.  A user may have access to one or many
    tenants with different roles in each.

    Rules:
    - If no rows exist for a user_id → deny access (admin role bypasses this).
    - If exactly one row exists → auto-bind session to that tenant.
    - If multiple rows exist → show tenant selection dropdown.

    Effective role resolution (at /select-tenant):
    - If ``role`` is set on this row, use it for the tenant-scoped JWT.
    - Otherwise, fall back to ``UserORM.role`` (the user's global default role).
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
    # Per-tenant role override.  NULL means "use UserORM.role".
    role = Column(String(50), nullable=True)
    # Audit: which user granted this access (NULL for seed / legacy rows).
    granted_by = Column(String(36), nullable=True)
    granted_at = Column(DateTime, default=lambda: datetime.utcnow())

    __table_args__ = (UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant"),)

    def __repr__(self):
        return (
            f"<UserTenantAccess user={self.user_id} tenant={self.tenant_id}"
            f" role={self.role}>"
        )
