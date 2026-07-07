#!/usr/bin/env python
"""EVL-05 -- Snap scorer vs correlation groups.

After a blind ingest, score the snap decisions that Abeyance Memory persisted
against the EVL-03 answer key. This produces THE number: does the engine find
planted correlations it has never seen?

Inputs
------
Two DB tables (read-only, SQLAlchemy sync):

  * ``abeyance_fragment`` -- fragment ``id`` <-> alarm ``source_ref``
    mapping, plus the fragment ``event_timestamp``.
  * ``snap_decision_record`` -- one row per candidate that reached the scoring
    stage, with ``new_fragment_id``, ``candidate_fragment_id``,
    ``evaluated_at`` and a ``decision`` in {SNAP, NEAR_MISS, AFFINITY, NONE}.

The answer key (EVL-03 ``--out-answers`` JSONL) has one line per correlation
group of size >= 2::

    {"group_id": ..., "alarm_ids": [...], "domains": [...], "span_seconds": ...}

Definitions
-----------
* **True pairs** -- every unordered alarm-id pair within an answer group.
* **Predicted (SNAP) pairs** -- the unordered
  ``(new_fragment.source_ref, candidate_fragment.source_ref)`` for every
  ``snap_decision_record`` row whose ``decision == 'SNAP'``. ``NEAR_MISS`` is
  reported separately and never counted as a positive prediction.
* **Retrieval pairs** -- the unordered fragment/alarm pair for EVERY
  ``snap_decision_record`` row regardless of decision. This measures the
  retrieval stage: did the partner even reach scoring?

Metrics (all in [0, 1] except the time-to-snap seconds)
-------------------------------------------------------
* ``pair_precision``      = |SNAP_pairs & true| / |SNAP_pairs|
* ``pair_recall``         = |SNAP_pairs & true| / |true|
* ``near_miss_recall``    = |near_miss_pairs & true| / |true|
* ``retrieval_recall``    = |retrieval_pairs & true| / |true|
* ``candidates_evaluated_total`` = number of snap_decision_record rows scored
* ``time_to_snap`` seconds = evaluated_at - (older fragment's event_timestamp),
  computed per SNAP decision; reported as median and p90/p95/p99.

A pair contributes to a metric only when BOTH of its alarm ids are present in
the answer key's alarm universe (i.e. both belong to some group of size >= 2);
otherwise it is irrelevant to the recall/precision question and is skipped for
the intersection numerators, but SNAP pairs are still counted in the
precision *denominator* so precision honestly penalises spurious snaps.

Usage
-----
Score a live tenant::

    python scripts/eval/score_snaps.py \
        --dsn postgresql+psycopg2://user:pw@host/db \
        --tenant-id six_telecom \
        --answers answers.jsonl \
        --out score.json

Offline self-test (no DB)::

    python scripts/eval/score_snaps.py --self-test
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from statistics import median
from typing import Iterable


# --------------------------------------------------------------------------- #
# Pure metric core (no DB, no I/O) -- this is what --self-test exercises.
# --------------------------------------------------------------------------- #

def unordered_pair(a: str, b: str) -> tuple[str, str]:
    """Order-independent, hashable key for an unordered pair of alarm ids."""
    a, b = str(a), str(b)
    return (a, b) if a <= b else (b, a)


def true_pairs_from_answers(answer_groups: Iterable[dict]) -> set[tuple[str, str]]:
    """All unordered alarm-id pairs within each answer group (size >= 2)."""
    pairs: set[tuple[str, str]] = set()
    for group in answer_groups:
        alarm_ids = [str(a) for a in group.get("alarm_ids", [])]
        n = len(alarm_ids)
        for i in range(n):
            for j in range(i + 1, n):
                if alarm_ids[i] != alarm_ids[j]:
                    pairs.add(unordered_pair(alarm_ids[i], alarm_ids[j]))
    return pairs


def _safe_ratio(numer: int, denom: int) -> float:
    """numer/denom, but 0.0 when the denominator is 0 (never divide-by-zero)."""
    return (numer / denom) if denom else 0.0


def compute_metrics(
    *,
    true_pairs: set[tuple[str, str]],
    snap_pairs: set[tuple[str, str]],
    near_miss_pairs: set[tuple[str, str]],
    retrieval_pairs: set[tuple[str, str]],
    candidates_evaluated_total: int,
    snap_time_to_snap_seconds: list[float],
) -> dict:
    """Compute all EVL-05 metrics from pre-built pair sets.

    Kept pure so the self-test can assert exact values with hand-built inputs.
    """
    snap_true = snap_pairs & true_pairs
    near_true = near_miss_pairs & true_pairs
    retrieval_true = retrieval_pairs & true_pairs

    pair_precision = _safe_ratio(len(snap_true), len(snap_pairs))
    pair_recall = _safe_ratio(len(snap_true), len(true_pairs))
    near_miss_recall = _safe_ratio(len(near_true), len(true_pairs))
    retrieval_recall = _safe_ratio(len(retrieval_true), len(true_pairs))

    times = sorted(float(t) for t in snap_time_to_snap_seconds)
    if times:
        tts = {
            "count": len(times),
            "median": median(times),
            "p90": _percentile(times, 90),
            "p95": _percentile(times, 95),
            "p99": _percentile(times, 99),
            "min": times[0],
            "max": times[-1],
        }
    else:
        tts = {
            "count": 0,
            "median": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "min": None,
            "max": None,
        }

    return {
        "true_pairs_total": len(true_pairs),
        "snap_pairs_total": len(snap_pairs),
        "snap_pairs_correct": len(snap_true),
        "near_miss_pairs_total": len(near_miss_pairs),
        "retrieval_pairs_total": len(retrieval_pairs),
        "candidates_evaluated_total": candidates_evaluated_total,
        "pair_precision": pair_precision,
        "pair_recall": pair_recall,
        "near_miss_recall": near_miss_recall,
        "retrieval_recall": retrieval_recall,
        "time_to_snap_seconds": tts,
    }


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolation percentile over an already-sorted list."""
    if not sorted_values:
        raise ValueError("percentile of empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


# --------------------------------------------------------------------------- #
# DB layer -- only imported/used in the live path.
# --------------------------------------------------------------------------- #

def _load_from_db(dsn: str, tenant_id: str) -> dict:
    """Read fragments + snap decisions for a tenant. Returns raw pieces.

    Returns a dict with:
      * ``frag_source_ref``   {fragment_id -> alarm_id (source_ref)}
      * ``frag_event_ts``     {fragment_id -> event_timestamp (aware datetime)}
      * ``decisions``         list of (new_id, cand_id, decision, evaluated_at)
    """
    # Imported lazily so --self-test needs neither SQLAlchemy nor a DB.
    from sqlalchemy import create_engine, text

    engine = create_engine(dsn)
    frag_source_ref: dict[str, str] = {}
    frag_event_ts: dict[str, datetime] = {}
    decisions: list[tuple[str, str, str, datetime]] = []

    with engine.connect() as conn:
        frag_rows = conn.execute(
            text(
                "SELECT id, source_ref, event_timestamp "
                "FROM abeyance_fragment WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )
        for fid, source_ref, event_ts in frag_rows:
            key = str(fid)
            if source_ref is not None:
                frag_source_ref[key] = str(source_ref)
            frag_event_ts[key] = event_ts

        dec_rows = conn.execute(
            text(
                "SELECT new_fragment_id, candidate_fragment_id, decision, "
                "evaluated_at FROM snap_decision_record WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )
        for new_id, cand_id, decision, evaluated_at in dec_rows:
            decisions.append((str(new_id), str(cand_id), str(decision), evaluated_at))

    engine.dispose()
    return {
        "frag_source_ref": frag_source_ref,
        "frag_event_ts": frag_event_ts,
        "decisions": decisions,
    }


def _as_aware(dt: datetime | None) -> datetime | None:
    """Coerce a naive datetime to UTC-aware; leave aware/None untouched."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def build_pairs_from_db_rows(db: dict) -> dict:
    """Turn raw DB rows into the pair sets + time list ``compute_metrics`` needs.

    Only decisions whose BOTH fragments resolve to a ``source_ref`` (alarm id)
    can form an alarm-space pair; unresolved rows are counted (they still count
    toward ``candidates_evaluated_total``) but cannot contribute to any pair set.
    """
    frag_source_ref = db["frag_source_ref"]
    frag_event_ts = db["frag_event_ts"]
    decisions = db["decisions"]

    snap_pairs: set[tuple[str, str]] = set()
    near_miss_pairs: set[tuple[str, str]] = set()
    retrieval_pairs: set[tuple[str, str]] = set()
    snap_times: list[float] = []

    for new_id, cand_id, decision, evaluated_at in decisions:
        new_ref = frag_source_ref.get(new_id)
        cand_ref = frag_source_ref.get(cand_id)
        if new_ref is None or cand_ref is None or new_ref == cand_ref:
            # Cannot map to a distinct alarm pair -- retrieval stat can't use it.
            continue
        pair = unordered_pair(new_ref, cand_ref)
        retrieval_pairs.add(pair)
        if decision == "SNAP":
            snap_pairs.add(pair)
            tts = _time_to_snap_seconds(
                new_id, cand_id, evaluated_at, frag_event_ts
            )
            if tts is not None:
                snap_times.append(tts)
        elif decision == "NEAR_MISS":
            near_miss_pairs.add(pair)

    return {
        "snap_pairs": snap_pairs,
        "near_miss_pairs": near_miss_pairs,
        "retrieval_pairs": retrieval_pairs,
        "snap_time_to_snap_seconds": snap_times,
        "candidates_evaluated_total": len(decisions),
    }


def _time_to_snap_seconds(
    new_id: str,
    cand_id: str,
    evaluated_at: datetime | None,
    frag_event_ts: dict[str, datetime],
) -> float | None:
    """evaluated_at - min(event_timestamp of the two fragments), in seconds.

    Returns None when a needed timestamp is missing.
    """
    evaluated_at = _as_aware(evaluated_at)
    ts_new = _as_aware(frag_event_ts.get(new_id))
    ts_cand = _as_aware(frag_event_ts.get(cand_id))
    candidates = [t for t in (ts_new, ts_cand) if t is not None]
    if evaluated_at is None or not candidates:
        return None
    older = min(candidates)
    return (evaluated_at - older).total_seconds()


# --------------------------------------------------------------------------- #
# Live entry point
# --------------------------------------------------------------------------- #

def _read_answers(path: str) -> list[dict]:
    """Read the EVL-03 answer-key JSONL (one group per line)."""
    groups: list[dict] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                groups.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                raise SystemExit(
                    f"answers file {path}: malformed JSON on line {line_no}: {exc}"
                )
    return groups


def run_live(dsn: str, tenant_id: str, answers_path: str, out_path: str | None) -> dict:
    """Full live scoring: read DB + answers, compute metrics, write/print."""
    answer_groups = _read_answers(answers_path)
    true_pairs = true_pairs_from_answers(answer_groups)

    db = _load_from_db(dsn, tenant_id)
    pieces = build_pairs_from_db_rows(db)

    metrics = compute_metrics(
        true_pairs=true_pairs,
        snap_pairs=pieces["snap_pairs"],
        near_miss_pairs=pieces["near_miss_pairs"],
        retrieval_pairs=pieces["retrieval_pairs"],
        candidates_evaluated_total=pieces["candidates_evaluated_total"],
        snap_time_to_snap_seconds=pieces["snap_time_to_snap_seconds"],
    )
    metrics["tenant_id"] = tenant_id
    metrics["answer_groups_total"] = len(answer_groups)

    _emit(metrics, out_path)
    return metrics


def _emit(metrics: dict, out_path: str | None) -> None:
    """Print a human summary and optionally write the full JSON."""
    payload = json.dumps(metrics, indent=2, default=str)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(payload + "\n")
    print(payload)


def _assert_ratios_bounded(metrics: dict) -> None:
    """Guard: every ratio metric must be within [0, 1]."""
    for key in ("pair_precision", "pair_recall", "near_miss_recall", "retrieval_recall"):
        val = metrics[key]
        assert 0.0 <= val <= 1.0, f"{key}={val} out of [0,1]"


# --------------------------------------------------------------------------- #
# Self-test (no DB) -- 4-row synthetic answer/prediction fixture.
# --------------------------------------------------------------------------- #

def self_test() -> bool:
    """Assert known metric values on a hand-built fixture. Returns pass/fail.

    Fixture design
    --------------
    Answer key -- two groups::

        G1: {a1, a2, a3}   -> true pairs {a1a2, a1a3, a2a3}   (3 pairs)
        G2: {a4, a5}       -> true pair  {a4a5}               (1 pair)
                                                    => 4 true pairs total

    Four fragments-worth of snap_decision_record rows (the "4-row fixture"):

        row1  SNAP       (a1, a2)   -> TRUE  positive
        row2  SNAP       (a1, x9)   -> FALSE positive (x9 not in any group)
        row3  NEAR_MISS  (a2, a3)   -> near-miss, true pair
        row4  NONE       (a4, a5)   -> retrieved only, true pair

    Expected metrics
    ----------------
      snap_pairs        = {a1a2, a1x9}                -> total 2
      snap_true         = {a1a2}                      -> 1
      pair_precision    = 1/2 = 0.5
      pair_recall       = 1/4 = 0.25
      near_miss_pairs   = {a2a3};  near_true = {a2a3} -> near_miss_recall = 1/4
      retrieval_pairs   = {a1a2, a1x9, a2a3, a4a5}
      retrieval_true    = {a1a2, a2a3, a4a5}          -> retrieval_recall = 3/4
      candidates_evaluated_total = 4
      time_to_snap: both SNAP rows resolve timestamps. SNAP(a1,a2): older ts is
                    f1@t0, evaluated_at t0+60s -> 60s. SNAP(a1,x9): older ts is
                    f1@t0 (fx also @t0), evaluated_at t0+60s -> 60s.
                    => count=2, median=60.0s
    """
    answers = [
        {"group_id": "G1", "alarm_ids": ["a1", "a2", "a3"]},
        {"group_id": "G2", "alarm_ids": ["a4", "a5"]},
    ]
    true_pairs = true_pairs_from_answers(answers)

    # Emulate the DB rows: fragments f1..f6, x9-fragment fx, event timestamps.
    frag_source_ref = {
        "f1": "a1", "f2": "a2", "f3": "a3",
        "f4": "a4", "f5": "a5", "fx": "x9",
    }
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    frag_event_ts = {
        "f1": base,                                   # a1 @ t0
        "f2": datetime(2026, 1, 1, 0, 1, 0, tzinfo=timezone.utc),  # a2 @ t0+60s
        "f3": base,
        "f4": base,
        "f5": base,
        "fx": base,   # x9 @ t0
    }
    # evaluated_at for the SNAP(a1,a2) row is t0+60s -> older ts is f1@t0 -> 60s.
    ev = datetime(2026, 1, 1, 0, 1, 0, tzinfo=timezone.utc)
    decisions = [
        ("f1", "f2", "SNAP", ev),        # a1,a2  TRUE positive, tts=60s
        ("f1", "fx", "SNAP", ev),        # a1,x9  FALSE positive
        ("f2", "f3", "NEAR_MISS", ev),   # a2,a3  near-miss
        ("f4", "f5", "NONE", ev),        # a4,a5  retrieved only
    ]
    db = {
        "frag_source_ref": frag_source_ref,
        "frag_event_ts": frag_event_ts,
        "decisions": decisions,
    }
    pieces = build_pairs_from_db_rows(db)
    metrics = compute_metrics(
        true_pairs=true_pairs,
        snap_pairs=pieces["snap_pairs"],
        near_miss_pairs=pieces["near_miss_pairs"],
        retrieval_pairs=pieces["retrieval_pairs"],
        candidates_evaluated_total=pieces["candidates_evaluated_total"],
        snap_time_to_snap_seconds=pieces["snap_time_to_snap_seconds"],
    )

    expected = {
        "true_pairs_total": 4,
        "snap_pairs_total": 2,
        "snap_pairs_correct": 1,
        "near_miss_pairs_total": 1,
        "retrieval_pairs_total": 4,
        "candidates_evaluated_total": 4,
        "pair_precision": 0.5,
        "pair_recall": 0.25,
        "near_miss_recall": 0.25,
        "retrieval_recall": 0.75,
    }

    ok = True
    failures: list[str] = []
    for key, want in expected.items():
        got = metrics[key]
        if isinstance(want, float):
            close = abs(got - want) < 1e-9
        else:
            close = got == want
        if not close:
            ok = False
            failures.append(f"  {key}: expected {want}, got {got}")

    # time_to_snap: both SNAP rows contribute a real duration of 60s each.
    tts = metrics["time_to_snap_seconds"]
    if tts["count"] != 2 or abs((tts["median"] or -1) - 60.0) > 1e-9:
        ok = False
        failures.append(
            f"  time_to_snap_seconds: expected count=2 median=60.0, got {tts}"
        )

    # Every ratio must be bounded.
    try:
        _assert_ratios_bounded(metrics)
    except AssertionError as exc:  # pragma: no cover - defensive
        ok = False
        failures.append(f"  bounds: {exc}")

    print(json.dumps(metrics, indent=2, default=str))
    if ok:
        print("SELF-TEST: PASS")
    else:
        print("SELF-TEST: FAIL")
        for line in failures:
            print(line)
    return ok


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="EVL-05 -- score persisted snap decisions vs the EVL-03 answer key.",
    )
    p.add_argument("--dsn", help="SQLAlchemy sync postgres DSN")
    p.add_argument("--tenant-id", help="tenant id to score")
    p.add_argument("--answers", help="EVL-03 answer-key JSONL path")
    p.add_argument("--out", help="output JSON path (optional; also printed)")
    p.add_argument(
        "--self-test",
        action="store_true",
        help="run the offline self-test (no DB) and exit",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.self_test:
        return 0 if self_test() else 1

    missing = [
        flag
        for flag, val in (("--dsn", args.dsn), ("--tenant-id", args.tenant_id), ("--answers", args.answers))
        if not val
    ]
    if missing:
        print(
            "error: live scoring requires " + ", ".join(missing)
            + " (or pass --self-test)",
            file=sys.stderr,
        )
        return 2

    metrics = run_live(args.dsn, args.tenant_id, args.answers, args.out)
    _assert_ratios_bounded(metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
