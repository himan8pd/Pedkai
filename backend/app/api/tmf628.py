"""
TMF628 Performance Management API Router (v4.0.0)

Adapts internal KPIMetricORM records to TMF628 PerformanceMeasurement.
"""

from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.app.core.database import get_db
from backend.app.core.security import get_current_user, TMF642_READ
from backend.app.models.kpi_orm import KPIMetricORM
from backend.app.models.tmf628_models import (
    PerformanceMeasurement, 
    PerformanceIndicatorSpecification,
    PerformanceIndicatorSpecificationRef
)

router = APIRouter()


@router.get("/performanceMeasurement", response_model=List[PerformanceMeasurement])
async def list_measurements(
    entity_id: Optional[str] = None,
    metric_name: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user=Security(get_current_user, scopes=[TMF642_READ])
):
    """
    List performance measurements with TMF-compliant filtering.
    Note: We reuse tmf642:alarm:read scope for general monitoring read access.
    """
    query = db.query(KPIMetricORM)
    
    if entity_id:
        query = query.filter(KPIMetricORM.entity_id == entity_id)
    if metric_name:
        query = query.filter(KPIMetricORM.metric_name == metric_name)
    if start_time:
        query = query.filter(KPIMetricORM.timestamp >= start_time)
    if end_time:
        query = query.filter(KPIMetricORM.timestamp <= end_time)
        
    results = query.order_by(desc(KPIMetricORM.timestamp)).limit(limit).all()
    
    return [
        PerformanceMeasurement(
            id=f"{r.entity_id}_{r.metric_name}_{r.timestamp.isoformat()}",
            observationTime=r.timestamp,
            measurementValue=r.value,
            performanceIndicatorSpecification=PerformanceIndicatorSpecificationRef(
                id=r.metric_name,
                name=r.metric_name
            )
        ) for r in results
    ]


@router.get("/performanceIndicatorSpecification", response_model=List[PerformanceIndicatorSpecification])
async def list_indicator_specs(
    current_user=Security(get_current_user, scopes=[TMF642_READ])
):
    """List available KPI types (Static catalog for MVP)."""
    # In a real system, this would be queried from a metadata registry
    specs = [
        PerformanceIndicatorSpecification(
            id="throughput_mbps",
            name="Throughput",
            description="Mean user throughput in Mbps",
            unitOfMeasure="Mbps"
        ),
        PerformanceIndicatorSpecification(
            id="latency_ms",
            name="Latency",
            description="End-to-end RTT in milliseconds",
            unitOfMeasure="ms"
        ),
        PerformanceIndicatorSpecification(
            id="prb_utilization",
            name="PRB Utilization",
            description="Physical Resource Block utilization percentage",
            unitOfMeasure="%"
        )
    ]
    return specs
