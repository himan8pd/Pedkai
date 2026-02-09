"""
Anomaly Detection Service for ANOps.

Provides statistical and rule-based anomaly detection on KPI metric streams.
"""

import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.kpi_orm import KPIMetricORM

class AnomalyDetector:
    """
    detects anomalies in KPI streams using statistical methods.
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_historical_window(
        self, 
        entity_id: str, 
        metric_name: str, 
        window_hours: int = 24
    ) -> List[float]:
        """
        Retrieves historical values for a metric to establish a baseline.
        """
        since = datetime.utcnow() - timedelta(hours=window_hours)
        
        query = (
            select(KPIMetricORM.value)
            .where(KPIMetricORM.entity_id == entity_id)
            .where(KPIMetricORM.metric_name == metric_name)
            .where(KPIMetricORM.timestamp >= since)
            .order_by(KPIMetricORM.timestamp.asc())
        )
        
        result = await self.session.execute(query)
        values = [row[0] for row in result.all()]
        return values

    def is_anomaly_zscore(
        self, 
        current_value: float, 
        historical_values: List[float], 
        threshold: float = 3.0
    ) -> Dict[str, Any]:
        """
        Detects anomaly using Z-score (standard deviations from mean).
        """
        if len(historical_values) < 5:
            return {"is_anomaly": False, "reason": "Insufficient historical data"}
            
        mean = np.mean(historical_values)
        std = np.std(historical_values)
        
        if std == 0:
            return {"is_anomaly": current_value != mean, "score": 0.0, "mean": mean}
            
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
        # 1. Store the metric
        new_metric = KPIMetricORM(
            tenant_id=tenant_id,
            entity_id=entity_id,
            metric_name=metric_name,
            value=value,
            tags=tags or {}
        )
        self.session.add(new_metric)
        # We don't commit yet to keep it in the same transaction if needed,
        # but for baseline we might need the previous values.
        
        # 2. Get baseline
        history = await self.get_historical_window(entity_id, metric_name)
        
        # 3. Check for anomaly
        result = self.is_anomaly_zscore(value, history)
        
        if result["is_anomaly"]:
            print(f"🚨 ANOMALY DETECTED: {entity_id} {metric_name} = {value} (Score: {result['score']})")
            
        return result
