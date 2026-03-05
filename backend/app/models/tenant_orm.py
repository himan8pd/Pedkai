from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, String

from backend.app.core.database import Base


class TenantORM(Base):
    """
    ORM Model for Multi-tenant isolation.

    The primary key ``id`` is a short, human-readable slug string such as
    ``"casinolimit"`` or ``"pedkai_synthetic_01"``.  This is the value that
    appears in every ``tenant_id`` column across the database and inside
    JWT tokens — no UUIDs, no indirection.

    ``display_name`` is an optional prettier label shown in the UI
    (e.g. "CasinoLimit" instead of "casinolimit").  If not set, the
    frontend should fall back to ``id``.
    """

    __tablename__ = "tenants"

    id = Column(String(100), primary_key=True)
    display_name = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Tenant {self.id}>"

    @property
    def label(self) -> str:
        """Return display_name if set, otherwise fall back to id."""
        return self.display_name or self.id
