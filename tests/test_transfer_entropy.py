"""Tests for Transfer Entropy causal inference implementation.

Covers:
- Directional asymmetry: TE(X->Y) > TE(Y->X) for a known causal pair
- Near-zero TE for two independent Gaussian series
- Significance: p_value < 0.05 for causal pair, p_value > 0.05 for independent
- Factory creates correct implementations
"""

import sys
import os

import numpy as np
import pytest

# Allow imports from the worktree root regardless of invocation directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.app.services.causal.transfer_entropy import TransferEntropyMethod
from backend.app.services.causal.granger import GrangerMethod
from backend.app.services.causal.base import CausalResult, CausalInferenceMethod
from backend.app.services.causal.factory import CausalMethodFactory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def causal_pair():
    """Y_t = X_{t-1} + noise — X Granger/TE-causes Y at lag 1."""
    np.random.seed(42)
    n = 500
    x = np.random.randn(n)
    noise = 0.1 * np.random.randn(n)
    y = np.zeros(n)
    y[1:] = x[:-1] + noise[1:]
    y[0] = noise[0]
    return x, y


@pytest.fixture
def independent_pair():
    """Two fully independent Gaussian series — no causal relationship."""
    np.random.seed(42)
    n = 500
    x = np.random.randn(n)
    y = np.random.randn(n)
    return x, y


@pytest.fixture
def te_method_fast():
    """TransferEntropyMethod with low permutation count for test speed."""
    method = TransferEntropyMethod(k=5)
    method.n_permutations = 20
    return method


# ---------------------------------------------------------------------------
# Transfer Entropy: directional asymmetry
# ---------------------------------------------------------------------------

def test_te_causal_direction_dominant(causal_pair, te_method_fast):
    """TE(X->Y) should be strictly greater than TE(Y->X) for a known causal pair."""
    x, y = causal_pair
    result_xy = te_method_fast.compute(x, y, lag=1)
    result_yx = te_method_fast.compute(y, x, lag=1)
    assert result_xy.score > result_yx.score, (
        f"Expected TE(X->Y)={result_xy.score:.4f} > TE(Y->X)={result_yx.score:.4f}"
    )


# ---------------------------------------------------------------------------
# Transfer Entropy: near-zero for independent series
# ---------------------------------------------------------------------------

def test_te_independent_near_zero(independent_pair, te_method_fast):
    """TE should be close to zero for two independent Gaussian series."""
    x, y = independent_pair
    result = te_method_fast.compute(x, y, lag=1)
    assert result.score < 0.5, (
        f"Expected near-zero TE for independent series, got {result.score:.4f}"
    )


# ---------------------------------------------------------------------------
# Transfer Entropy: significance
# ---------------------------------------------------------------------------

def test_te_causal_pair_significant(causal_pair, te_method_fast):
    """p_value < 0.05 for the known causal direction X->Y."""
    x, y = causal_pair
    result = te_method_fast.compute(x, y, lag=1)
    assert result.p_value < 0.05, (
        f"Expected significant TE for causal pair, got p={result.p_value:.4f}"
    )
    assert result.is_causal is True


def test_te_independent_not_significant(independent_pair, te_method_fast):
    """p_value > 0.05 for two independent series."""
    x, y = independent_pair
    result = te_method_fast.compute(x, y, lag=1)
    assert result.p_value > 0.05, (
        f"Expected non-significant TE for independent pair, got p={result.p_value:.4f}"
    )
    assert result.is_causal is False


# ---------------------------------------------------------------------------
# CausalResult fields
# ---------------------------------------------------------------------------

def test_causal_result_fields(causal_pair, te_method_fast):
    """CausalResult must carry all expected fields with correct types."""
    x, y = causal_pair
    result = te_method_fast.compute(x, y, lag=1)
    assert isinstance(result, CausalResult)
    assert isinstance(result.score, float)
    assert isinstance(result.p_value, float)
    assert isinstance(result.is_causal, bool)
    assert result.method == "transfer_entropy"


# ---------------------------------------------------------------------------
# Factory: correct implementations returned
# ---------------------------------------------------------------------------

def test_factory_creates_transfer_entropy():
    """CausalMethodFactory.create('transfer_entropy') returns TransferEntropyMethod."""
    method = CausalMethodFactory.create("transfer_entropy")
    assert isinstance(method, TransferEntropyMethod)
    assert isinstance(method, CausalInferenceMethod)


def test_factory_creates_granger():
    """CausalMethodFactory.create('granger') returns GrangerMethod."""
    method = CausalMethodFactory.create("granger")
    assert isinstance(method, GrangerMethod)
    assert isinstance(method, CausalInferenceMethod)


def test_factory_unknown_key_raises():
    """CausalMethodFactory.create raises KeyError for unknown method names."""
    with pytest.raises(KeyError, match="No causal method registered"):
        CausalMethodFactory.create("nonexistent_method")


def test_factory_available_lists_both():
    """Both 'granger' and 'transfer_entropy' appear in available() output."""
    available = CausalMethodFactory.available()
    assert "granger" in available
    assert "transfer_entropy" in available
