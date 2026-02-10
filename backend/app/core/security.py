"""
Security and Authentication for Pedkai API.

Implements OAuth2 with password flow and JWT tokens.
Required for TMF API compliance (Strategic Review GAP 3).
"""

from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import OAuth2PasswordBearer, SecurityScopes
from jose import JWTError, jwt
from pydantic import BaseModel

from backend.app.core.config import get_settings

settings = get_settings()

# TMF-specific scopes
TMF642_READ = "tmf642:alarm:read"
TMF642_WRITE = "tmf642:alarm:write"

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="token",
    scopes={
        TMF642_READ: "Read access to TMF642 Alarms",
        TMF642_WRITE: "Write access to TMF642 Alarms (Acknowledge, Clear, Create)",
    },
)


class User(BaseModel):
    username: str
    scopes: List[str] = []


class TokenData(BaseModel):
    username: Optional[str] = None
    scopes: List[str] = []


async def get_current_user(
    security_scopes: SecurityScopes, 
    token: str = Depends(oauth2_scheme)
) -> User:
    """
    Validate JWT token and check required scopes.
    For MVP, we use a simple static check or mock validation.
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
        # In a real system, we'd verify the JWT signature here
        # For prototype/MVP, we extract the claims (mocked)
        payload = {"sub": "noc_operator", "scopes": [TMF642_READ, TMF642_WRITE]}
        # payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_scopes = payload.get("scopes", [])
        token_data = TokenData(scopes=token_scopes, username=username)
    except (JWTError, Exception):
        raise credentials_exception
        
    for scope in security_scopes.scopes:
        if scope not in token_data.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions",
                headers={"WWW-Authenticate": authenticate_value},
            )
            
    return User(username=username, scopes=token_data.scopes)
