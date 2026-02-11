"""
Integration tests for AI-Driven Capacity Planning.
"""
import pytest
from httpx import AsyncClient
from uuid import UUID

@pytest.mark.asyncio
async def test_create_densification_request(client: AsyncClient):
    """
    Test creating a densification request and getting the optimized plan.
    """
    payload = {
        "region_name": "Maharashtra-Pune",
        "budget_limit": 100000.0,
        "target_kpi": "prb_utilization",
        "parameters": {"min_sites": 1}
    }
    
    # 1. Create request
    response = await client.post("/api/v1/capacity/", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["region_name"] == "Maharashtra-Pune"
    assert data["status"] == "completed" # Optimization is synchronous in our service for now
    request_id = data["id"]
    
    # 2. Get Plan
    response = await client.get(f"/api/v1/capacity/{request_id}/plan")
    assert response.status_code == 200
    plan = response.json()
    assert plan["request_id"] == request_id
    assert plan["total_estimated_cost"] > 0
    assert len(plan["site_placements"]) > 0
    assert "rationale" in plan
