
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Boolean
from backend.app.core.database import Base

class TenantORM(Base):
    """
    ORM Model for Multi-tenant isolation.
    """
    __tablename__ = "tenants"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Tenant {self.name}>"
