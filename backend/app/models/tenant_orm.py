import re
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.orm import validates

from backend.app.core.database import Base

# Canonical tenant ID format: lowercase letters, digits, underscores.
# 3-100 chars, must start with a letter.
TENANT_ID_PATTERN = re.compile(r'^[a-z][a-z0-9_]{2,99}$')


def normalise_tenant_slug(slug: str) -> str:
    """Strip punctuation variants to detect near-miss duplicates.

    Maps ``six-telecom``, ``six_telecom``, ``SixTelecom`` → ``sixtelecom``.
    """
    return slug.lower().replace("-", "").replace("_", "").replace(" ", "")


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

    **Naming convention**: ``^[a-z][a-z0-9_]{2,99}$`` — lowercase,
    underscores only, no hyphens, no spaces.
    """

    __tablename__ = "tenants"

    id = Column(String(100), primary_key=True)
    display_name = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    @validates('id')
    def validate_tenant_id(self, _key: str, value: str) -> str:
        if not TENANT_ID_PATTERN.match(value):
            raise ValueError(
                f"Invalid tenant_id '{value}'. Must match {TENANT_ID_PATTERN.pattern} "
                f"(lowercase alphanumeric + underscores, 3-100 chars, starts with a letter)."
            )
        return value

    def __repr__(self):
        return f"<Tenant {self.id}>"

    @property
    def label(self) -> str:
        """Return display_name if set, otherwise fall back to id."""
        return self.display_name or self.id
