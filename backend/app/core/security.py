"""
Security and Authentication for Pedkai API.

Implements OAuth2 with password flow and JWT tokens.
Required for TMF API compliance (Strategic Review GAP 3).
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import OAuth2PasswordBearer, SecurityScopes
from jose import JWTError, jwt
from pydantic import BaseModel

from backend.app.core.config import get_settings

settings = get_settings()

# TMF-specific scopes
TMF642_READ = "tmf642:alarm:read"
TMF642_WRITE = "tmf642:alarm:write"

# Capacity Planning scopes (Phase 13 Remediation)
CAPACITY_READ = "capacity:plan:read"
CAPACITY_WRITE = "capacity:plan:write"

# CX Intelligence scopes (Phase 14)
CX_READ = "cx:intelligence:read"
CX_WRITE = "cx:intelligence:write"

# Topology scopes (WS1)
TOPOLOGY_READ = "topology:read"
TOPOLOGY_READ_FULL = "topology:read_full"
TOPOLOGY_REVENUE = "topology:revenue"

# Incident lifecycle scopes (WS2)
INCIDENT_READ = "incident:read"
INCIDENT_APPROVE_SITREP = "incident:approve_sitrep"
INCIDENT_APPROVE_ACTION = "incident:approve_action"
INCIDENT_CLOSE = "incident:close"

# Autonomous shield scopes (WS5)
AUTONOMOUS_READ = "autonomous:read"

# Policy scopes (WS8)
POLICY_READ = "policy:read"
POLICY_WRITE = "policy:write"

# User management scope (tenant_admin / admin)
USERS_MANAGE = "users:manage"

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="api/v1/auth/token",
    scopes={
        TMF642_READ: "Read access to TMF642 Alarms",
        TMF642_WRITE: "Write access to TMF642 Alarms (Acknowledge, Clear, Create)",
        CAPACITY_READ: "Read access to Capacity Investment Plans",
        CAPACITY_WRITE: "Create and Optimize Capacity Plans",
        CX_READ: "Read access to Customer Impact & Churn Risk",
        CX_WRITE: "Trigger Proactive Care Automation",
        TOPOLOGY_READ: "Read topology entities and relationships",
        TOPOLOGY_READ_FULL: "Read full topology graph (rate-limited)",
        TOPOLOGY_REVENUE: "Read revenue-at-risk topology data",
        INCIDENT_READ: "Read incident records and reasoning chains",
        INCIDENT_APPROVE_SITREP: "Approve incident situation reports (Human Gate 1)",
        INCIDENT_APPROVE_ACTION: "Approve incident resolution actions (Human Gate 2)",
        INCIDENT_CLOSE: "Close resolved incidents (Human Gate 3)",
        AUTONOMOUS_READ: "Read autonomous shield detections and recommendations",
        POLICY_READ: "Read policy engine configuration",
        POLICY_WRITE: "Modify policy engine configuration",
        USERS_MANAGE: "Create and manage users within the current tenant",
    },
)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """
    Generate a signed JWT token.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)

    # Ensure tenant_id is explicitly handled if present
    if "tenant_id" in data:
        to_encode["tenant_id"] = data["tenant_id"]

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, settings.secret_key, algorithm=settings.algorithm
    )
    return encoded_jwt


# Role definitions
class Role:
    ADMIN = "admin"
    TENANT_ADMIN = "tenant_admin"  # Manages users within a single tenant
    OPERATOR = "operator"
    VIEWER = "viewer"
    SHIFT_LEAD = "shift_lead"  # Operator + sitrep approval
    ENGINEER = "engineer"  # Operator + action approval


# Role hierarchy/scopes
_OPERATOR_BASE_SCOPES = [
    TMF642_READ,
    TMF642_WRITE,
    CAPACITY_READ,
    CAPACITY_WRITE,
    CX_READ,
    CX_WRITE,
    "metrics:read",
    TOPOLOGY_READ,
    TOPOLOGY_READ_FULL,
    TOPOLOGY_REVENUE,
    INCIDENT_READ,
    AUTONOMOUS_READ,
    POLICY_READ,
]

ROLE_SCOPES = {
    Role.ADMIN: [
        TMF642_READ,
        TMF642_WRITE,
        CAPACITY_READ,
        CAPACITY_WRITE,
        CX_READ,
        CX_WRITE,
        "metrics:read",
        "admin:all",
        TOPOLOGY_READ,
        TOPOLOGY_READ_FULL,
        TOPOLOGY_REVENUE,
        INCIDENT_READ,
        INCIDENT_APPROVE_SITREP,
        INCIDENT_APPROVE_ACTION,
        INCIDENT_CLOSE,
        AUTONOMOUS_READ,
        POLICY_READ,
        POLICY_WRITE,
        USERS_MANAGE,
    ],
    # Tenant admin: read-only view of the platform + user management for own tenant.
    # Cannot approve/close incidents or write policies — purely administrative.
    Role.TENANT_ADMIN: [
        TMF642_READ,
        CAPACITY_READ,
        CX_READ,
        "metrics:read",
        TOPOLOGY_READ,
        INCIDENT_READ,
        AUTONOMOUS_READ,
        POLICY_READ,
        USERS_MANAGE,
    ],
    Role.OPERATOR: _OPERATOR_BASE_SCOPES,
    Role.VIEWER: [
        TMF642_READ,
        CAPACITY_READ,
        CX_READ,
        "metrics:read",
        TOPOLOGY_READ,
        INCIDENT_READ,
        AUTONOMOUS_READ,
        POLICY_READ,
    ],
    Role.SHIFT_LEAD: _OPERATOR_BASE_SCOPES + [INCIDENT_APPROVE_SITREP],
    Role.ENGINEER: _OPERATOR_BASE_SCOPES + [INCIDENT_APPROVE_ACTION],
}


class User(BaseModel):
    username: str
    user_id: Optional[str] = None
    role: str
    scopes: List[str] = []
    tenant_id: Optional[str] = None


class TokenData(BaseModel):
    username: Optional[str] = None
    user_id: Optional[str] = None
    role: Optional[str] = None
    scopes: List[str] = []
    tenant_id: Optional[str] = None


def _resolve_sub_claim(payload: dict) -> tuple:
    """Resolve ``sub`` claim from JWT payload.

    New tokens set ``sub`` = user_id (UUID) with ``username`` as a
    separate claim.  Legacy tokens set ``sub`` = username with
    ``user_id`` as a separate claim.  This helper detects the format
    and returns ``(user_id, username)`` in both cases.
    """
    sub = payload.get("sub", "")
    # UUIDs are 36 chars with 4 hyphens (e.g. "550e8400-e29b-41d4-a716-446655440000")
    if sub and "-" in sub and len(sub) == 36:
        # New format: sub = user_id
        user_id = sub
        username = payload.get("username", sub)
    else:
        # Legacy format: sub = username
        username = sub
        user_id = payload.get("user_id")
    return user_id, username


def decode_token_string(token: str) -> User:
    """Decode a JWT token string directly (for SSE/WebSocket endpoints).

    EventSource API cannot send Authorization headers, so the token
    must be passed as a query parameter instead.
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id, username = _resolve_sub_claim(payload)
        if not username and not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        tenant_id = payload.get("tenant_id")
        role = payload.get("role", Role.VIEWER)
        scopes = payload.get("scopes", ROLE_SCOPES.get(role, []))
        return User(
            username=username,
            user_id=user_id,
            tenant_id=tenant_id,
            role=role,
            scopes=scopes,
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_current_user(
    security_scopes: SecurityScopes, token: str = Depends(oauth2_scheme)
) -> User:
    """
    Validate JWT token and check required scopes based on Role-Based Access Control.
    """
    if security_scopes.scopes:
        authenticate_value = f'Bearer scope="{security_scopes.scope_str}"'
    else:
        authenticate_value = "Bearer"

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": authenticate_value},
    )

    try:
        # Real JWT validation
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        user_id, username = _resolve_sub_claim(payload)
        if not username and not user_id:
            raise credentials_exception

        role: str = payload.get("role", Role.VIEWER)
        tenant_id: Optional[str] = payload.get("tenant_id")
        # Assign scopes based on role if not present in token
        token_scopes = payload.get("scopes", ROLE_SCOPES.get(role, []))

        token_data = TokenData(
            username=username,
            user_id=user_id,
            role=role,
            scopes=token_scopes,
            tenant_id=tenant_id,
        )
    except (JWTError, Exception):
        raise credentials_exception

    for scope in security_scopes.scopes:
        if scope not in token_data.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Not enough permissions. Required scope: {scope}",
                headers={"WWW-Authenticate": authenticate_value},
            )

    from backend.app.core.logging import tenant_id_ctx

    tenant_id_ctx.set(tenant_id)

    return User(
        username=username,
        user_id=user_id,
        role=role,
        scopes=token_data.scopes,
        tenant_id=tenant_id,
    )
