"""
Authentication router for Pedkai.
Provides endpoints for obtaining JWT tokens.
"""

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from backend.app.core.config import get_settings
from backend.app.core.security import create_access_token, Role, ROLE_SCOPES

router = APIRouter()
settings = get_settings()

# Mock user database for PoC (In production, use a real User table)
MOCK_USERS_DB = {
    "admin": {
        "username": "admin",
        "hashed_password": "fakehashed_admin", # In reality, use passlib.hash.bcrypt.hash
        "role": Role.ADMIN,
    },
    "operator": {
        "username": "operator",
        "hashed_password": "fakehashed_operator",
        "role": Role.OPERATOR,
    }
}

@router.post("/token")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """
    Standard OAuth2 /token endpoint to exchange credentials for a JWT.
    """
    user = MOCK_USERS_DB.get(form_data.username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Simple password check for PoC (In production, use hashed_password verification)
    if form_data.password != user["username"]: # password is the username for mock
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    
    # Generate scopes based on role
    role = user["role"]
    scopes = ROLE_SCOPES.get(role, [])
    
    access_token = create_access_token(
        data={"sub": user["username"], "role": role, "scopes": scopes},
        expires_delta=access_token_expires
    )
    
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "role": role,
        "scopes": scopes
    }
