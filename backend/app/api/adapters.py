"""
Adapters API (P5.4)

Endpoints to manage Netconf adapter test connections and dry-run operations.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.database import get_db
from backend.app.core.security import get_current_user, Security, AUTONOMOUS_READ
from backend.app.services.netconf_adapter import NetconfSession

router = APIRouter(prefix="/api/v1/adapters", tags=["Adapters"])


@router.post("/netconf/connect")
async def netconf_connect(payload: dict, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    host = payload.get("host")
    username = payload.get("username")
    if not host:
        raise HTTPException(status_code=400, detail="host required")
    session = NetconfSession(host=host, username=username)
    ok = session.connect(use_mock=True)
    return {"connected": ok, "vendor": session.vendor}


@router.post("/netconf/validate")
async def netconf_validate(payload: dict, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    host = payload.get("host")
    operation = payload.get("operation")
    parameters = payload.get("parameters", {})
    if not host or not operation:
        raise HTTPException(status_code=400, detail="host and operation required")
    session = NetconfSession(host=host)
    session.connect(use_mock=True)
    result = session.validate(operation, parameters)
    return result


@router.post("/netconf/execute")
async def netconf_execute(payload: dict, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    host = payload.get("host")
    operation = payload.get("operation")
    parameters = payload.get("parameters", {})
    if not host or not operation:
        raise HTTPException(status_code=400, detail="host and operation required")
    session = NetconfSession(host=host)
    session.connect(use_mock=True)
    result = session.execute(operation, parameters)
    return result
