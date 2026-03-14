import os

import numpy as np
from scipy.special import digamma
from sklearn.neighbors import NearestNeighbors

from .base import CausalInferenceMethod, CausalResult


class TransferEntropyMethod(CausalInferenceMethod):
    """KNN-based Transfer Entropy using the Kraskov estimator.

    Transfer Entropy TE(X->Y) measures the reduction in uncertainty about
    Y_future given knowledge of both Y_past and X_past, compared to Y_past alone.

    Reference: Kraskov et al. (2004), "Estimating mutual information",
    Physical Review E 69, 066138.
    """

    def __init__(self, k: int = 5):
        self.k = k  # KNN neighbors
        self.n_permutations = int(os.environ.get("TE_PERMUTATION_COUNT", "100"))
        self.alpha = 0.05

    def _knn_entropy(self, data: np.ndarray) -> float:
        """Kraskov entropy estimator.

        H = digamma(n) - digamma(k) + d * mean(log(2*r))

        Args:
            data: Array of shape (n_samples, n_dims).

        Returns:
            Estimated differential entropy.
        """
        n, d = data.shape
        nbrs = NearestNeighbors(n_neighbors=self.k + 1, metric="chebyshev").fit(data)
        distances, _ = nbrs.kneighbors(data)
        r = distances[:, self.k]  # distance to k-th neighbor (index 0 is self)
        entropy = digamma(n) - digamma(self.k) + d * np.mean(np.log(2 * r + 1e-10))
        return entropy

    def _transfer_entropy(self, x: np.ndarray, y: np.ndarray, lag: int) -> float:
        """Compute TE(X->Y) using the chain-rule decomposition.

        TE(X->Y) = H(Y_future | Y_past) - H(Y_future | Y_past, X_past)
                 = H(Y_future, Y_past) + H(Y_past, X_past)
                   - H(Y_future, Y_past, X_past) - H(Y_past)

        Args:
            x: Candidate cause series of length n.
            y: Candidate effect series of length n.
            lag: Number of time steps for past embedding.

        Returns:
            Non-negative transfer entropy estimate.
        """
        y_future = y[lag:].reshape(-1, 1)
        y_past = y[:-lag].reshape(-1, 1)
        x_past = x[:-lag].reshape(-1, 1)

        joint_full = np.hstack([y_future, y_past, x_past])   # (Y_fut, Y_past, X_past)
        joint_marginal = np.hstack([y_future, y_past])        # (Y_fut, Y_past)

        h_joint_full = self._knn_entropy(joint_full)
        h_joint_marginal = self._knn_entropy(joint_marginal)
        h_y_past_x_past = self._knn_entropy(np.hstack([y_past, x_past]))
        h_y_past = self._knn_entropy(y_past)

        te = h_joint_marginal + h_y_past_x_past - h_joint_full - h_y_past
        return max(0.0, te)  # TE >= 0 by definition

    def compute(self, x: np.ndarray, y: np.ndarray, lag: int = 1) -> CausalResult:
        """Compute Transfer Entropy from x to y with permutation significance test.

        The null hypothesis is that x and y are independent (no causal influence).
        Significance is assessed by comparing the observed TE against the
        distribution of TE values obtained by randomly permuting x, which
        destroys any temporal coupling while preserving the marginal distribution.

        Args:
            x: Candidate cause series.
            y: Candidate effect series.
            lag: Time lag for embedding.

        Returns:
            CausalResult with TE score, empirical p-value, and significance flag.
        """
        te_observed = self._transfer_entropy(x, y, lag)

        # Permutation test: shuffle x to obtain null distribution
        te_permuted = []
        rng = np.random.default_rng(42)
        for _ in range(self.n_permutations):
            x_shuffled = rng.permutation(x)
            te_perm = self._transfer_entropy(x_shuffled, y, lag)
            te_permuted.append(te_perm)

        # p-value = fraction of permuted TE values >= observed TE
        p_value = float(np.mean([t >= te_observed for t in te_permuted]))

        return CausalResult(
            score=te_observed,
            p_value=p_value,
            is_causal=p_value < self.alpha,
            method="transfer_entropy",
        )
