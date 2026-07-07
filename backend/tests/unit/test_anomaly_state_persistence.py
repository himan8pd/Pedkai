"""
PRF-02: AnomalyDetector baseline persistence across restarts.

Verifies that Welford accumulator state survives a save/load round-trip
(so a process restart does not re-learn baselines and re-fire anomalies),
and that a corrupt or missing state file starts the detector clean with a
WARNING rather than crashing.
"""

import logging

from backend.app.telemetry.fragment_bridge import AnomalyDetector


def _feed(detector: AnomalyDetector, entity: str, kpi: str, values):
    """Feed values, returning the last z-score reported by check()."""
    last_z = None
    for v in values:
        z = detector.check(entity, kpi, v)
        if z is not None:
            last_z = z
    return last_z


def test_round_trip_preserves_zscore(tmp_path):
    """Feed 100 values, save, reload into a fresh detector; the next value's
    z-score must match the un-restarted detector to 6 decimals."""
    # z_threshold=0.0 so check() always returns the raw z-score.
    entity, kpi = "cell-42", "prb_util"
    values = [10.0 + (i % 7) * 1.3 - (i % 3) * 0.9 for i in range(100)]

    # Detector A: continuous (no restart)
    det_a = AnomalyDetector(z_threshold=0.0)
    _feed(det_a, entity, kpi, values)

    # Detector B: same history, then persisted and reloaded into a fresh one
    det_b = AnomalyDetector(z_threshold=0.0)
    _feed(det_b, entity, kpi, values)

    state_path = str(tmp_path / "anomaly_state.json")
    det_b.save_state(state_path)

    det_c = AnomalyDetector(z_threshold=0.0)
    det_c.load_state(state_path)

    # The next observation must yield an identical z-score.
    next_value = 42.0
    z_continuous = det_a.check(entity, kpi, next_value)
    z_restored = det_c.check(entity, kpi, next_value)

    assert z_continuous is not None
    assert z_restored is not None
    assert round(z_continuous, 6) == round(z_restored, 6)


def test_save_is_atomic_and_reloadable(tmp_path):
    """State written to disk reloads with identical accumulator internals."""
    det = AnomalyDetector(z_threshold=0.0)
    _feed(det, "e1", "k1", [float(i) for i in range(20)])
    _feed(det, "e2", "k2", [float(i) * 2 for i in range(20)])

    path = str(tmp_path / "state.json")
    det.save_state(path)

    restored = AnomalyDetector(z_threshold=0.0)
    restored.load_state(path)

    orig = det._accumulators
    new = restored._accumulators
    assert set(orig.keys()) == set(new.keys())
    for key in orig:
        assert orig[key].n == new[key].n
        assert round(orig[key].mean, 12) == round(new[key].mean, 12)
        assert round(orig[key].m2, 12) == round(new[key].m2, 12)


def test_corrupt_file_starts_clean_with_warning(tmp_path, caplog):
    """A corrupt state file must not raise — detector starts empty and warns."""
    path = tmp_path / "corrupt.json"
    path.write_text("{not valid json at all ][")

    # Fresh detector reloading a corrupt snapshot at startup.
    det = AnomalyDetector(z_threshold=0.0)
    with caplog.at_level(logging.WARNING):
        det.load_state(str(path))

    assert det._accumulators == {}
    assert any("unreadable" in r.message or "malformed" in r.message
               for r in caplog.records)


def test_missing_file_starts_clean_with_warning(tmp_path, caplog):
    """A missing state file must not raise — detector starts empty and warns."""
    path = str(tmp_path / "does_not_exist.json")

    det = AnomalyDetector(z_threshold=0.0)
    with caplog.at_level(logging.WARNING):
        det.load_state(path)

    assert det._accumulators == {}
    assert any("not found" in r.message for r in caplog.records)
