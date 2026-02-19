"""
Authentication router for Pedkai.
Provides endpoints for obtaining JWT tokens.
"""

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.core.security import create_access_token, Role, ROLE_SCOPES
from backend.app.services import auth_service

router = APIRouter()
settings = get_settings()

@router.post("/token")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Standard OAuth2 /token endpoint to exchange credentials for a JWT.
    """
    user = await auth_service.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)

    # Generate scopes based on role
    role = Role(user.role)
    scopes = ROLE_SCOPES.get(role, [])
    tenant_id = user.tenant_id

    access_token = create_access_token(
        data={"sub": user.username, "role": role, "scopes": scopes, "tenant_id": tenant_id},
        expires_delta=access_token_expires
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": role,
        "scopes": scopes
    }
