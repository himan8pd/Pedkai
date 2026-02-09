"""
Causal Analysis Service for ANOps.

Provides Granger Causality tests to determine if one metric "causes" another.
This moves Pedkai from "Correlation" to "Causation" for root cause analysis.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.kpi_orm import KPIMetricORM


class CausalAnalyzer:
    """
    Performs Granger Causality tests on time-series metrics.
    
    Granger Causality: If past values of X help predict Y (beyond Y's own history),
    then X "Granger-causes" Y.
    """
    
    # Finding #1: Increase minimum observations to ensure statistical power (Telco MTTR context)
    MIN_OBSERVATIONS = 100 
    
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_available_metrics(self, entity_id: str, hours: int = 24) -> List[str]:
        """
        Finding #3: Dynamically discovers what metrics exist for an entity.
        Eliminates hardcoded candidate lists.
        """
        since = datetime.utcnow() - timedelta(hours=hours)
        from sqlalchemy import func
        
        query = (
            select(KPIMetricORM.metric_name)
            .where(KPIMetricORM.entity_id == entity_id)
            .where(KPIMetricORM.timestamp >= since)
            .distinct()
        )
        
        result = await self.session.execute(query)
        return [row[0] for row in result.all()]

    async def _fetch_metric_series(
        self,
        entity_id: str,
        metric_name: str,
        hours: int = 24
    ) -> List[float]:
        """
        Fetches a time-ordered series of metric values from TimescaleDB.
        """
        since = datetime.utcnow() - timedelta(hours=hours)
        
        query = (
            select(KPIMetricORM.value)
            .where(KPIMetricORM.entity_id == entity_id)
            .where(KPIMetricORM.metric_name == metric_name)
            .where(KPIMetricORM.timestamp >= since)
            .order_by(KPIMetricORM.timestamp.asc())
        )
        
        result = await self.session.execute(query)
        return [row[0] for row in result.all()]

    def _ensure_stationary(self, series: List[float]) -> Tuple[List[float], bool]:
        """
        Finding #2: Tests for stationarity using Augmented Dickey-Fuller.
        Returns (processed_series, was_differenced).
        """
        from statsmodels.tsa.stattools import adfuller
        
        if len(series) < 20: # ADF needs some points
            return series, False
            
        try:
            # autolag='AIC' chooses the best lag for the ADF test
            result = adfuller(series, autolag='AIC')
            p_value = result[1]
            
            if p_value > 0.05:  # Non-stationary (fail to reject null)
                # Apply first-order differencing
                diffed = list(np.diff(series))
                return diffed, True
                
            return series, False
        except Exception:
            # Fallback if ADF fails (e.g. constant series)
            return series, False

    async def test_granger_causality(
        self,
        entity_id: str,
        cause_metric: str,
        effect_metric: str,
        max_lag: int = 4,
        significance_level: float = 0.05
    ) -> Dict[str, Any]:
        """
        Tests if `cause_metric` Granger-causes `effect_metric` for a given entity.
        """
        from statsmodels.tsa.stattools import grangercausalitytests
        
        # Fetch series
        cause_series = await self._fetch_metric_series(entity_id, cause_metric)
        effect_series = await self._fetch_metric_series(entity_id, effect_metric)
        
        # Finding #1: Sample size guard
        if len(cause_series) < self.MIN_OBSERVATIONS or len(effect_series) < self.MIN_OBSERVATIONS:
            return {
                "causes": False,
                "p_value": 1.0,
                "cause_metric": cause_metric,
                "effect_metric": effect_metric,
                "error": f"Insufficient statistical power. Need {self.MIN_OBSERVATIONS} points, got {min(len(cause_series), len(effect_series))}"
            }
        
        # Finding #2: Stationarity Checks
        cause_series, c_diffed = self._ensure_stationary(cause_series)
        effect_series, e_diffed = self._ensure_stationary(effect_series)
        
        # Align lengths (differencing removes 1 point)
        min_len = min(len(cause_series), len(effect_series))
        cause_series = cause_series[:min_len]
        effect_series = effect_series[:min_len]
        
        data = np.column_stack([effect_series, cause_series])
        
        try:
            results = grangercausalitytests(data, maxlag=max_lag, verbose=False)
            
            best_p_value = 1.0
            best_lag = 0
            for lag in range(1, max_lag + 1):
                p_value = results[lag][0]['ssr_ftest'][1]
                if p_value < best_p_value:
                    best_p_value = p_value
                    best_lag = lag
            
            return {
                "causes": best_p_value < significance_level,
                "p_value": round(best_p_value, 4),
                "best_lag": best_lag,
                "cause_metric": cause_metric,
                "effect_metric": effect_metric,
                "stationarity_fixed": c_diffed or e_diffed
            }
        except Exception as e:
            return {"causes": False, "error": str(e), "cause_metric": cause_metric, "effect_metric": effect_metric}

    async def find_causes_for_anomaly(
        self,
        entity_id: str,
        anomalous_metric: str,
        max_lag: int = 4
    ) -> List[Dict[str, Any]]:
        """
        Dynamically finds causes for an anomaly by discovering all available metrics.
        """
        # Finding #3: Dynamic discovery
        metrics = await self.get_available_metrics(entity_id)
        
        causal_results = []
        for candidate in metrics:
            if candidate == anomalous_metric:
                continue
                
            result = await self.test_granger_causality(
                entity_id=entity_id,
                cause_metric=candidate,
                effect_metric=anomalous_metric,
                max_lag=max_lag
            )
            
            if result.get("causes"):
                causal_results.append(result)
        
        causal_results.sort(key=lambda x: x.get("p_value", 1.0))
        return causal_results
