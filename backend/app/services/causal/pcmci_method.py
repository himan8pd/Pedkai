"""PCMCI causal graph discovery — wraps tigramite.pcmci.PCMCI.

If tigramite is unavailable, falls back to a pure-numpy approximation
that performs pairwise Granger-style conditional independence testing.
"""
import logging
import os
from dataclasses import dataclass
from typing import Optional
import numpy as np

from .base import CausalInferenceMethod, CausalResult

logger = logging.getLogger(__name__)

try:
    import tigramite
    import tigramite.data_processing as pp
    from tigramite.pcmci import PCMCI
    from tigramite.independence_tests.parcorr import ParCorr
    TIGRAMITE_AVAILABLE = True
    logger.info("tigramite available — using full PCMCI")
except ImportError:
    TIGRAMITE_AVAILABLE = False
    logger.warning("tigramite not available — using numpy fallback for PCMCI")


@dataclass
class CausalGraph:
    """Full causal graph from PCMCI."""
    var_names: list[str]
    edges: dict  # {(source, target, lag): (coefficient, p_value)}

    def summary(self) -> str:
        lines = [f"CausalGraph: {len(self.var_names)} variables, {len(self.edges)} edges"]
        for (src, tgt, lag), (coef, pval) in sorted(self.edges.items(), key=lambda x: x[1][1]):
            if pval < 0.05:
                lines.append(f"  {src} --(lag {lag})--> {tgt}: coef={coef:.3f}, p={pval:.3f}")
        return "\n".join(lines)

    def is_significant_edge(self, source: str, target: str, alpha: float = 0.05) -> bool:
        """Check if any lag for source->target is significant."""
        return any(
            pval < alpha
            for (src, tgt, _lag), (_coef, pval) in self.edges.items()
            if src == source and tgt == target
        )


def _granger_f_test(y: np.ndarray, x: np.ndarray, lag: int) -> tuple[float, float]:
    """Simple Granger F-test for one (X->Y) pair at given lag."""
    n = len(y)
    if n <= lag + 2:
        return 0.0, 1.0

    # Restricted: Y predicted by Y_lag only
    Y = y[lag:]
    Y_lag = y[:n-lag].reshape(-1, 1)

    def ols(X, Y):
        XtX = X.T @ X + 1e-8 * np.eye(X.shape[1])
        coefs = np.linalg.solve(XtX, X.T @ Y)
        return coefs, Y - X @ coefs

    ones = np.ones((len(Y), 1))
    _, e_restricted = ols(np.hstack([ones, Y_lag]), Y)
    rss_r = e_restricted @ e_restricted

    # Unrestricted: Y predicted by Y_lag and X_lag
    X_lag = x[:n-lag].reshape(-1, 1)
    _, e_unrestricted = ols(np.hstack([ones, Y_lag, X_lag]), Y)
    rss_u = e_unrestricted @ e_unrestricted

    if rss_u < 1e-10 or rss_r <= rss_u:
        return 0.0, 1.0

    m = len(Y)
    k = 1  # one additional predictor
    F = ((rss_r - rss_u) / k) / (rss_u / (m - 3))

    from scipy import stats
    p_value = float(stats.f.sf(F, k, m - 3))
    coef = float(np.linalg.lstsq(np.hstack([ones, Y_lag, X_lag]), Y, rcond=None)[0][-1])
    return coef, p_value


class PCMCIMethod(CausalInferenceMethod):
    """PCMCI causal graph discovery. Uses tigramite if available, else numpy fallback."""

    def __init__(self):
        self.max_lag = int(os.environ.get("PCMCI_MAX_LAG", "6"))
        self.alpha = float(os.environ.get("PCMCI_ALPHA", "0.05"))
        self.nonlinear = os.environ.get("PCMCI_NONLINEAR", "false").lower() == "true"

    def compute_graph(self, data: np.ndarray, var_names: list[str], max_lag: int = None) -> CausalGraph:
        """Run PCMCI over multivariate time series.

        Args:
            data: shape (T, N) — T timesteps, N variables
            var_names: N variable names
            max_lag: override max_lag

        Returns CausalGraph with all significant edges.
        """
        if max_lag is None:
            max_lag = self.max_lag

        if TIGRAMITE_AVAILABLE:
            return self._compute_with_tigramite(data, var_names, max_lag)
        else:
            return self._compute_fallback(data, var_names, max_lag)

    def _compute_with_tigramite(self, data: np.ndarray, var_names: list[str], max_lag: int) -> CausalGraph:
        dataframe = pp.DataFrame(data, var_names=var_names)
        cond_ind_test = ParCorr(significance="analytic")
        pcmci = PCMCI(dataframe=dataframe, cond_ind_test=cond_ind_test, verbosity=0)
        results = pcmci.run_pcmci(tau_max=max_lag, pc_alpha=self.alpha)

        p_matrix = results["p_matrix"]    # shape (N, N, max_lag+1)
        val_matrix = results["val_matrix"]  # shape (N, N, max_lag+1)

        edges = {}
        N = len(var_names)
        for i in range(N):
            for j in range(N):
                for lag in range(1, max_lag + 1):
                    coef = float(val_matrix[i, j, lag])
                    pval = float(p_matrix[i, j, lag])
                    if pval < self.alpha:
                        edges[(var_names[i], var_names[j], lag)] = (coef, pval)

        return CausalGraph(var_names=var_names, edges=edges)

    def _compute_fallback(self, data: np.ndarray, var_names: list[str], max_lag: int) -> CausalGraph:
        """Pairwise Granger F-test fallback when tigramite unavailable."""
        N = data.shape[1]
        edges = {}
        for i in range(N):
            for j in range(N):
                if i == j:
                    continue
                for lag in range(1, min(max_lag + 1, 4)):
                    coef, pval = _granger_f_test(data[:, j], data[:, i], lag)
                    if pval < self.alpha:
                        edges[(var_names[i], var_names[j], lag)] = (coef, pval)
        return CausalGraph(var_names=var_names, edges=edges)

    def compute(self, x: np.ndarray, y: np.ndarray, lag: int) -> CausalResult:
        """Interface compliance: pairwise X->Y test via compute_graph."""
        data = np.column_stack([x, y])
        graph = self.compute_graph(data, ["X", "Y"], max_lag=lag)

        x_causes_y = any(
            src == "X" and tgt == "Y"
            for (src, tgt, _lag) in graph.edges
        )

        # Get best p-value for X->Y edges
        xy_edges = [(coef, pval) for (src, tgt, _lag), (coef, pval) in graph.edges.items()
                    if src == "X" and tgt == "Y"]

        if xy_edges:
            best_coef, best_pval = min(xy_edges, key=lambda e: e[1])
        else:
            best_coef, best_pval = 0.0, 1.0

        return CausalResult(
            score=abs(best_coef),
            p_value=best_pval,
            is_causal=x_causes_y,
            method="pcmci" if TIGRAMITE_AVAILABLE else "pcmci_fallback"
        )

    def name(self) -> str:
        return "pcmci"
