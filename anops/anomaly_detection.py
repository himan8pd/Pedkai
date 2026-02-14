"""
Anomaly Detection Service for ANOps.

Provides statistical and rule-based anomaly detection on KPI metric streams.
Optimized with a 'Hot Path' cache for baselines to ensure scalability.
"""

import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.kpi_orm import KPIMetricORM

class AnomalyDetector:
    """
    detects anomalies in KPI streams using statistical methods.
    
    Includes a class-level cache to avoid redundant historical DB queries.
    """
    
    # Simple Hot-Path Cache: {(tenant_id, entity_id, metric_name): (mean, std, expiry_time)}
    _baseline_cache: Dict[Tuple[str, str, str], Tuple[float, float, datetime]] = {}
    
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_baseline(
        self, 
        tenant_id: str,
        entity_id: str, 
        metric_name: str, 
        ttl_minutes: int = 60
    ) -> Tuple[float, float]:
        """
        Retrieves baseline (mean, std) from cache or DB.
        """
        cache_key = (tenant_id, entity_id, metric_name)
        now = datetime.now(timezone.utc)
        
        # Check cache
        if cache_key in self._baseline_cache:
            m, s, expiry = self._baseline_cache[cache_key]
            if now < expiry:
                return m, s

        # Cache miss or expired: Fetch from DB
        print(f"🔍 Cache Miss: Recalculating baseline for {tenant_id}:{entity_id}:{metric_name}...")
        since = now - timedelta(hours=24)
        
        query = (
            select(KPIMetricORM.value)
            .where(KPIMetricORM.tenant_id == tenant_id)
            .where(KPIMetricORM.entity_id == entity_id)
            .where(KPIMetricORM.metric_name == metric_name)
            .where(KPIMetricORM.timestamp >= since)
        )
        
        result = await self.session.execute(query)
        values = [row[0] for row in result.all()]
        
        if len(values) < 5:
            # Fallback for new entities
            return 0.0, 0.0
            
        mean = float(np.mean(values))
        std = float(np.std(values))
        
        # Update cache
        self._baseline_cache[cache_key] = (mean, std, now + timedelta(minutes=ttl_minutes))
        return mean, std

    def is_anomaly_zscore(
        self, 
        current_value: float, 
        mean: float,
        std: float,
        threshold: float = 3.0
    ) -> Dict[str, Any]:
        """
        Detects anomaly using Z-score (standard deviations from mean).
        """
        if std == 0:
            # If std is 0, any change from mean is an anomaly (or skip if mean is 0)
            is_anom = (current_value != mean) if mean != 0 else False
            return {"is_anomaly": is_anom, "score": 0.0, "mean": mean}
            
        z_score = abs(current_value - mean) / std
        
        return {
            "is_anomaly": z_score > threshold,
            "score": round(float(z_score), 2),
            "mean": round(float(mean), 2),
            "std": round(float(std), 2),
            "threshold": threshold
        }

    async def process_metric(
        self, 
        tenant_id: str,
        entity_id: str, 
        metric_name: str, 
        value: float,
        tags: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Processes a new metric value, stores it, and checks for anomalies.
        """
        # 1. Get baseline (Uses Hot-Path Cache)
        # Fetch from past data BEFORE adding the current point
        mean, std = await self.get_baseline(tenant_id, entity_id, metric_name)
        
        # 2. Store the metric (Batch ingestion point in real system)
        new_metric = KPIMetricORM(
            tenant_id=tenant_id,
            entity_id=entity_id,
            metric_name=metric_name,
            value=value,
            tags=tags or {}
        )
        self.session.add(new_metric)
        
        # 3. Check for anomaly
        if mean == 0 and std == 0:
            return {"is_anomaly": False, "reason": "Insufficient historical data"}
            
        result = self.is_anomaly_zscore(value, mean, std)
        
        if result["is_anomaly"]:
            print(f"🚨 ANOMALY DETECTED: {entity_id} {metric_name} = {value} (Score: {result['score']})")
            
        return result
