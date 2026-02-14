import asyncio
import httpx
import sys
import os
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app.core.config import get_settings

settings = get_settings()

async def test_auth(username, password):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "http://localhost:8000/api/v1/auth/token",
                data={"username": username, "password": password}
            )
            return response.status_code, response.json()
        except Exception as e:
            return None, str(e)

async def main():
    print(f"Testing with ADMIN_PASSWORD: {settings.admin_password}")
    print(f"Testing with OPERATOR_PASSWORD: {settings.operator_password}")

    # Test Admin
    status, result = await test_auth("admin", settings.admin_password)
    print(f"Admin login: Status {status}, Result: {result}")

    # Test Operator
    status, result = await test_auth("operator", settings.operator_password)
    print(f"Operator login: Status {status}, Result: {result}")

    # Test Fail
    status, result = await test_auth("admin", "wrongpassword")
    print(f"Wrong password login: Status {status}")

if __name__ == "__main__":
    asyncio.run(main())
