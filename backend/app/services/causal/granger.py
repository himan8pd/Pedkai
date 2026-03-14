import numpy as np
from statsmodels.tsa.stattools import grangercausalitytests

from .base import CausalInferenceMethod, CausalResult


class GrangerMethod(CausalInferenceMethod):
    """Granger causality test wrapping statsmodels grangercausalitytests.

    Tests whether x Granger-causes y: i.e., past values of x improve
    prediction of y beyond y's own history.
    """

    def __init__(self, alpha: float = 0.05):
        self.alpha = alpha

    def compute(self, x: np.ndarray, y: np.ndarray, lag: int = 1) -> CausalResult:
        """Run Granger causality test for x -> y at a given lag.

        Args:
            x: The candidate cause time series.
            y: The candidate effect time series.
            lag: Maximum lag to test.

        Returns:
            CausalResult with the F-test statistic and p-value at the given lag.
        """
        # grangercausalitytests expects a 2-column array: [effect, cause]
        data = np.column_stack([y, x])

        results = grangercausalitytests(data, maxlag=lag, verbose=False)

        # Extract the ssr_ftest (F-statistic) result at the requested lag
        lag_result = results[lag]
        f_stat, p_value, _, _ = lag_result[0]["ssr_ftest"]

        return CausalResult(
            score=float(f_stat),
            p_value=float(p_value),
            is_causal=float(p_value) < self.alpha,
            method="granger",
        )
