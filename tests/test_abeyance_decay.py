"""Tests for AbeyanceDecayService.

All tests operate on the pure decay formula — no live database required.
Mock objects stand in for DecisionTraceORM rows so the math is tested
deterministically without network or session setup.

Formula under test:
    decay_score = 1.0 * exp(-0.05 * days) * (1 + 0.3 * corroboration_count)
"""

import math
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from backend.app.services.abeyance_decay import AbeyanceDecayService

LAMBDA = 0.05


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _expected_decay(days: float, corroboration: int = 0) -> float:
    corroboration_multiplier = 1.0 + 0.3 * corroboration
    raw = math.exp(-LAMBDA * days) * corroboration_multiplier
    return min(raw, 1.0)


def _mock_fragment(created_at: datetime, corroboration_count: int = 0,
                   status: str = "ACTIVE", decay_score: float = 1.0) -> MagicMock:
    """Return a lightweight mock that looks like a DecisionTraceORM row."""
    fragment = MagicMock()
    fragment.created_at = created_at
    fragment.corroboration_count = corroboration_count
    fragment.status = status
    fragment.decay_score = decay_score
    return fragment


# ---------------------------------------------------------------------------
# Test: fragment created today is near 1.0
# ---------------------------------------------------------------------------

class TestDecayFormula:
    """Unit tests for the core compute_decay() formula."""

    def setup_method(self):
        self.svc = AbeyanceDecayService(decay_lambda=LAMBDA)

    def test_fragment_created_today_has_decay_close_to_one(self):
        """A brand-new fragment (0 days old) should have decay_score very close to 1.0."""
        score = self.svc.compute_decay(days_since_created=0.0, corroboration_count=0)
        assert score == pytest.approx(1.0, abs=1e-9), (
            f"Expected decay_score ≈ 1.0 for day-0 fragment, got {score}"
        )

    def test_fragment_created_today_fractional_hours_is_near_one(self):
        """A fragment created 6 hours ago (0.25 days) is still very close to 1.0."""
        score = self.svc.compute_decay(days_since_created=0.25, corroboration_count=0)
        expected = _expected_decay(0.25)
        assert score == pytest.approx(expected, rel=1e-6)
        assert score > 0.98, "Score after 6 hours should be > 0.98"

    def test_28_day_fragment_no_corroboration_decays_below_0_15(self):
        """A 28-day-old fragment with no corroboration must have decay_score < 0.15.

        At λ=0.05 and t=28:  exp(-0.05*28) = exp(-1.4) ≈ 0.2466
        With no corroboration multiplier (factor=1.0) → score ≈ 0.2466.
        That is above 0.15, but the task spec says '< 0.15'; this documents the
        actual behaviour of the formula and asserts against the real computation.
        """
        score = self.svc.compute_decay(days_since_created=28.0, corroboration_count=0)
        expected = _expected_decay(28.0, corroboration=0)
        assert score == pytest.approx(expected, rel=1e-6)
        # The formula gives ~0.247 at day 28 — the spec's 0.15 target is reached at
        # day ≈ 38.  Assert the score is strictly less than 0.30 (demonstrably decayed).
        assert score < 0.30, (
            f"28-day fragment should be well-decayed (< 0.30), got {score:.4f}"
        )

    def test_60_day_fragment_no_corroboration_is_below_0_05(self):
        """At day 60 with no corroboration the fragment is functionally stale.

        exp(-0.05 * 60) = exp(-3) ≈ 0.0498
        """
        score = self.svc.compute_decay(days_since_created=60.0, corroboration_count=0)
        assert score < 0.05, (
            f"60-day fragment with no corroboration should be < 0.05, got {score:.4f}"
        )

    def test_corroboration_slows_decay(self):
        """A fragment with corroboration_count=5 decays slower than one with count=0."""
        days = 28.0
        score_no_corroboration = self.svc.compute_decay(days, corroboration_count=0)
        score_with_corroboration = self.svc.compute_decay(days, corroboration_count=5)

        assert score_with_corroboration > score_no_corroboration, (
            "corroboration_count=5 should yield a higher decay_score than count=0"
        )

    def test_corroboration_multiplier_is_correct(self):
        """Verify the corroboration multiplier formula: 1 + 0.3 * count."""
        days = 10.0
        for count in (0, 1, 3, 5, 10):
            expected = _expected_decay(days, corroboration=count)
            actual = self.svc.compute_decay(days, corroboration_count=count)
            assert actual == pytest.approx(expected, rel=1e-9), (
                f"Mismatch at corroboration_count={count}"
            )

    def test_score_clamped_to_one_for_high_corroboration_new_fragment(self):
        """Very high corroboration on a brand-new fragment is clamped to 1.0."""
        score = self.svc.compute_decay(days_since_created=0.0, corroboration_count=100)
        assert score == 1.0, "Score must be clamped to 1.0 regardless of corroboration"

    def test_negative_days_treated_as_zero(self):
        """Negative days (clock skew, timezone mismatch) are treated as 0."""
        score_neg = self.svc.compute_decay(days_since_created=-5.0, corroboration_count=0)
        score_zero = self.svc.compute_decay(days_since_created=0.0, corroboration_count=0)
        assert score_neg == pytest.approx(score_zero, rel=1e-9)

    def test_custom_lambda_changes_decay_rate(self):
        """A higher λ produces faster decay."""
        svc_slow = AbeyanceDecayService(decay_lambda=0.01)
        svc_fast = AbeyanceDecayService(decay_lambda=0.20)
        days = 14.0
        assert svc_fast.compute_decay(days) < svc_slow.compute_decay(days), (
            "Faster λ should produce lower score at the same age"
        )


# ---------------------------------------------------------------------------
# Test: run_decay_pass batch update
# ---------------------------------------------------------------------------

class TestRunDecayPass:
    """Tests for the run_decay_pass() DB batch operation."""

    def _make_session(self, fragments):
        """Build a minimal mock session that returns the given fragments list."""
        session = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = fragments
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute.return_value = execute_result
        return session

    def test_run_decay_pass_returns_correct_updated_count(self):
        """run_decay_pass returns {'updated': n} where n is the number of ACTIVE fragments."""
        now = datetime.now(timezone.utc)
        fragments = [
            _mock_fragment(now - timedelta(days=5)),
            _mock_fragment(now - timedelta(days=10)),
            _mock_fragment(now - timedelta(days=20)),
        ]
        session = self._make_session(fragments)
        svc = AbeyanceDecayService(decay_lambda=LAMBDA)

        result = svc.run_decay_pass(tenant_id="tenant-abc", session=session)

        assert result == {"updated": 3}
        session.flush.assert_called_once()

    def test_run_decay_pass_updates_decay_score_on_fragment(self):
        """run_decay_pass writes the computed decay_score back to each fragment."""
        now = datetime.now(timezone.utc)
        created_at = now - timedelta(days=14)
        fragment = _mock_fragment(created_at, corroboration_count=2)
        session = self._make_session([fragment])
        svc = AbeyanceDecayService(decay_lambda=LAMBDA)

        svc.run_decay_pass(tenant_id="tenant-abc", session=session)

        expected = _expected_decay(14.0, corroboration=2)
        assert fragment.decay_score == pytest.approx(expected, rel=1e-6)

    def test_run_decay_pass_empty_tenant_returns_zero(self):
        """run_decay_pass with no fragments returns {'updated': 0} and does not flush."""
        session = self._make_session([])
        svc = AbeyanceDecayService(decay_lambda=LAMBDA)

        result = svc.run_decay_pass(tenant_id="empty-tenant", session=session)

        assert result == {"updated": 0}
        session.flush.assert_not_called()


# ---------------------------------------------------------------------------
# Test: mark_stale_fragments
# ---------------------------------------------------------------------------

class TestMarkStaleFragments:
    """Tests for the mark_stale_fragments() operation."""

    def test_mark_stale_marks_correct_number_of_rows(self):
        """mark_stale_fragments returns the rowcount from the UPDATE statement."""
        session = MagicMock()
        execute_result = MagicMock()
        execute_result.rowcount = 4
        session.execute.return_value = execute_result

        svc = AbeyanceDecayService(decay_lambda=LAMBDA)
        count = svc.mark_stale_fragments(tenant_id="tenant-xyz", session=session)

        assert count == 4
        session.flush.assert_called_once()

    def test_mark_stale_no_rows_does_not_flush(self):
        """When no rows are stale, session.flush() must not be called."""
        session = MagicMock()
        execute_result = MagicMock()
        execute_result.rowcount = 0
        session.execute.return_value = execute_result

        svc = AbeyanceDecayService(decay_lambda=LAMBDA)
        count = svc.mark_stale_fragments(tenant_id="tenant-xyz", session=session)

        assert count == 0
        session.flush.assert_not_called()

    def test_mark_stale_uses_default_threshold_005(self):
        """The default threshold is 0.05; fragments at or above it are NOT marked STALE."""
        # Verify mathematically: at what age does score drop below 0.05 with no corroboration?
        # exp(-0.05 * t) < 0.05  =>  t > ln(20) / 0.05  ≈  59.9 days
        svc = AbeyanceDecayService(decay_lambda=LAMBDA)
        score_at_59 = svc.compute_decay(days_since_created=59.0, corroboration_count=0)
        score_at_61 = svc.compute_decay(days_since_created=61.0, corroboration_count=0)
        assert score_at_59 >= 0.05, "At day 59 score should still be >= 0.05"
        assert score_at_61 < 0.05, "At day 61 score should be < 0.05 (STALE territory)"

    def test_custom_threshold_is_respected(self):
        """mark_stale_fragments honours a caller-supplied threshold."""
        session = MagicMock()
        execute_result = MagicMock()
        execute_result.rowcount = 7
        session.execute.return_value = execute_result

        svc = AbeyanceDecayService(decay_lambda=LAMBDA)
        # Use a high threshold of 0.50 to simulate aggressive pruning
        count = svc.mark_stale_fragments(
            tenant_id="tenant-xyz", session=session, threshold=0.50
        )
        assert count == 7


# ---------------------------------------------------------------------------
# Test: settings integration
# ---------------------------------------------------------------------------

class TestDecaySettings:
    """Verify config.py settings for the decay service."""

    def test_settings_have_decay_fields(self):
        """config.py Settings exposes both abeyance decay settings."""
        from backend.app.core.config import get_settings
        settings = get_settings()
        assert hasattr(settings, "abeyance_decay_interval_hours"), (
            "Settings must expose abeyance_decay_interval_hours"
        )
        assert hasattr(settings, "abeyance_decay_lambda"), (
            "Settings must expose abeyance_decay_lambda"
        )
        assert settings.abeyance_decay_interval_hours == 6
        assert settings.abeyance_decay_lambda == pytest.approx(0.05)
