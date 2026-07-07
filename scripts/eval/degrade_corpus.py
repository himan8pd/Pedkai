#!/usr/bin/env python3
"""EVL-07 — Degraded-input corpus transforms.

Simulate hostile real-world feeds by applying deterministic transforms to a
JSONL corpus of events:

  * drop     -- randomly remove X% of events
  * dup      -- randomly duplicate Y% of events (keeping IDENTICAL source_ref,
                so downstream dedup behaviour is what gets measured)
  * jitter   -- perturb each event timestamp by +/- Z minutes
  * truncate -- truncate the content string of W% of events

All transforms are deterministic under a fixed --seed (they use a single
``random.Random(seed)`` instance). The output JSONL is re-sorted by timestamp.

Each corpus line is expected to be a JSON object with at least:
  * an ``id`` / ``source_ref`` identifier
  * a ``timestamp`` field (ISO-8601 string or epoch seconds)
  * a ``content`` string

The exact field names are auto-detected with sensible fallbacks so the tool
works against a range of corpus shapes; a synthetic corpus is used for
``--verify``.

Usage:
    python -m scripts.eval.degrade_corpus --corpus in.jsonl --out out.jsonl \
        --drop-pct 30 --dup-pct 10 --jitter-minutes 5 --truncate-pct 20 --seed 42

    python -m scripts.eval.degrade_corpus --verify
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import random
import sys
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Field detection helpers
# ---------------------------------------------------------------------------

_TIMESTAMP_KEYS = ("timestamp", "ts", "time", "event_time", "@timestamp", "created_at")
_ID_KEYS = ("source_ref", "id", "_id", "event_id", "uid")
_CONTENT_KEYS = ("content", "message", "text", "body", "description")

_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def _first_present_key(record: Dict[str, Any], candidates: Tuple[str, ...]) -> Optional[str]:
    for key in candidates:
        if key in record:
            return key
    return None


def _parse_timestamp(value: Any) -> dt.datetime:
    """Parse an ISO-8601 string or epoch number into a tz-aware datetime."""
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc)
    if isinstance(value, str):
        s = value.strip()
        # epoch encoded as string
        try:
            return dt.datetime.fromtimestamp(float(s), tz=dt.timezone.utc)
        except (ValueError, OverflowError):
            pass
        # ISO-8601 (accept trailing Z)
        try:
            parsed = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            return parsed
        except ValueError:
            pass
    # Unparseable -> epoch (keeps ordering deterministic instead of crashing)
    return _EPOCH


def _format_timestamp(original: Any, new_value: dt.datetime) -> Any:
    """Render ``new_value`` in the same representation as ``original``."""
    if isinstance(original, (int, float)):
        return int(new_value.timestamp()) if isinstance(original, int) else new_value.timestamp()
    if isinstance(original, str):
        s = original.strip()
        try:
            float(s)
            return str(new_value.timestamp())
        except ValueError:
            pass
    # default: ISO-8601 with trailing Z when input was Z-suffixed
    iso = new_value.astimezone(dt.timezone.utc).isoformat()
    if isinstance(original, str) and original.strip().endswith("Z"):
        iso = iso.replace("+00:00", "Z")
    return iso


def _sort_key(record: Dict[str, Any]) -> Tuple[float, str]:
    ts_key = _first_present_key(record, _TIMESTAMP_KEYS)
    ts = _parse_timestamp(record[ts_key]) if ts_key else _EPOCH
    id_key = _first_present_key(record, _ID_KEYS)
    ident = str(record.get(id_key, "")) if id_key else ""
    return (ts.timestamp(), ident)


# ---------------------------------------------------------------------------
# Core transform
# ---------------------------------------------------------------------------

def _pick_exact(rng: random.Random, n_total: int, pct: float) -> List[int]:
    """Deterministically select exactly floor(n_total * pct / 100) indices."""
    count = int(n_total * pct / 100.0)
    if count <= 0:
        return []
    count = min(count, n_total)
    return rng.sample(range(n_total), count)


def degrade(
    records: List[Dict[str, Any]],
    *,
    drop_pct: float = 0.0,
    dup_pct: float = 0.0,
    jitter_minutes: float = 0.0,
    truncate_pct: float = 0.0,
    seed: int = 0,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Apply the degradation transforms and return (output, manifest).

    Deterministic under ``seed``. Order of operations: drop -> dup -> jitter ->
    truncate -> re-sort by timestamp.
    """
    rng = random.Random(seed)
    n_in = len(records)

    manifest: Dict[str, Any] = {
        "seed": seed,
        "input_count": n_in,
        "transforms": {
            "drop_pct": drop_pct,
            "dup_pct": dup_pct,
            "jitter_minutes": jitter_minutes,
            "truncate_pct": truncate_pct,
        },
    }

    # 1. DROP -----------------------------------------------------------------
    drop_idx = set(_pick_exact(rng, n_in, drop_pct))
    survivors = [copy.deepcopy(r) for i, r in enumerate(records) if i not in drop_idx]
    n_dropped = len(drop_idx)

    # 2. DUP ------------------------------------------------------------------
    # Percentage is measured against the ORIGINAL input size, per acceptance
    # criteria (dup=10 on a 1000-line file adds exactly 100). Duplicates are
    # sampled from the surviving records; if the requested duplicate count
    # exceeds the number of survivors we sample with replacement so the exact
    # additive count still holds.
    n_dup_target = int(n_in * dup_pct / 100.0)
    if survivors and n_dup_target > 0:
        if n_dup_target <= len(survivors):
            dup_source_idx = rng.sample(range(len(survivors)), n_dup_target)
        else:
            dup_source_idx = [rng.randrange(len(survivors)) for _ in range(n_dup_target)]
    else:
        dup_source_idx = []
    duplicates = [copy.deepcopy(survivors[i]) for i in dup_source_idx]
    # Duplicates keep IDENTICAL source_ref / id — no mutation of identity.
    working = survivors + duplicates
    n_dup = len(duplicates)

    # 3. JITTER ---------------------------------------------------------------
    n_jittered = 0
    if jitter_minutes and jitter_minutes > 0:
        bound_seconds = jitter_minutes * 60.0
        for rec in working:
            ts_key = _first_present_key(rec, _TIMESTAMP_KEYS)
            if ts_key is None:
                continue
            original = rec[ts_key]
            base = _parse_timestamp(original)
            delta = rng.uniform(-bound_seconds, bound_seconds)
            new_ts = base + dt.timedelta(seconds=delta)
            rec[ts_key] = _format_timestamp(original, new_ts)
            n_jittered += 1

    # 4. TRUNCATE -------------------------------------------------------------
    n_truncated = 0
    trunc_idx = set(_pick_exact(rng, len(working), truncate_pct))
    for i in trunc_idx:
        rec = working[i]
        c_key = _first_present_key(rec, _CONTENT_KEYS)
        if c_key is None or not isinstance(rec[c_key], str):
            continue
        original = rec[c_key]
        if not original:
            continue
        keep = max(1, len(original) // 2)
        rec[c_key] = original[:keep]
        n_truncated += 1

    # 5. RE-SORT --------------------------------------------------------------
    working.sort(key=_sort_key)

    manifest["counts"] = {
        "dropped": n_dropped,
        "duplicated": n_dup,
        "jittered": n_jittered,
        "truncated": n_truncated,
        "output_count": len(working),
    }
    return working, manifest


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive
                raise SystemExit(f"Malformed JSON on line {line_no} of {path}: {exc}")
    return records


def _write_jsonl(path: str, records: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True))
            fh.write("\n")


def _print_manifest(manifest: Dict[str, Any]) -> None:
    print("=" * 60)
    print("DEGRADE MANIFEST")
    print("=" * 60)
    print(f"  seed           : {manifest['seed']}")
    print(f"  input_count    : {manifest['input_count']}")
    t = manifest["transforms"]
    print("  transforms:")
    print(f"    drop_pct     : {t['drop_pct']}")
    print(f"    dup_pct      : {t['dup_pct']}")
    print(f"    jitter_minutes : {t['jitter_minutes']}")
    print(f"    truncate_pct : {t['truncate_pct']}")
    c = manifest["counts"]
    print("  results:")
    print(f"    dropped      : {c['dropped']}")
    print(f"    duplicated   : {c['duplicated']}")
    print(f"    jittered     : {c['jittered']}")
    print(f"    truncated    : {c['truncated']}")
    print(f"    output_count : {c['output_count']}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Synthetic corpus + verification
# ---------------------------------------------------------------------------

def _make_synthetic_corpus(n: int, seed: int = 0) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    records: List[Dict[str, Any]] = []
    # Space events 1 hour apart so that +/- (minutes) jitter can never push a
    # timestamp closer to a neighbouring grid point than its own; this keeps
    # the nearest-grid attribution in --verify unambiguous.
    for i in range(n):
        ts = base + dt.timedelta(hours=i)
        records.append(
            {
                "source_ref": f"evt-{i:06d}",
                "timestamp": ts.isoformat().replace("+00:00", "Z"),
                "content": f"synthetic event {i} " + ("x" * rng.randint(20, 80)),
            }
        )
    return records


def _run_verify() -> int:
    print("[verify] generating 1,000-line synthetic corpus ...")
    n = 1000
    corpus = _make_synthetic_corpus(n, seed=1)

    seed = 42
    drop_pct, dup_pct, jitter_minutes, truncate_pct = 30.0, 10.0, 5.0, 20.0

    out, manifest = degrade(
        corpus,
        drop_pct=drop_pct,
        dup_pct=dup_pct,
        jitter_minutes=jitter_minutes,
        truncate_pct=truncate_pct,
        seed=seed,
    )
    _print_manifest(manifest)

    failures: List[str] = []

    # drop=30 on 1000 -> 700 survivors; dup=10 measured against the original
    # 1000-line input -> exactly +100 duplicates.
    expected_survivors = 700
    expected_dup = 100  # 10% of the original 1000-line input
    expected_output = expected_survivors + expected_dup  # 800

    if manifest["counts"]["dropped"] != 300:
        failures.append(f"dropped expected 300, got {manifest['counts']['dropped']}")
    survivors_after_drop = n - manifest["counts"]["dropped"]
    if survivors_after_drop != expected_survivors:
        failures.append(
            f"survivors after drop expected {expected_survivors}, got {survivors_after_drop}"
        )
    if manifest["counts"]["duplicated"] != expected_dup:
        failures.append(
            f"duplicated expected {expected_dup}, got {manifest['counts']['duplicated']}"
        )
    if manifest["counts"]["output_count"] != expected_output:
        failures.append(
            f"output_count expected {expected_output}, got {manifest['counts']['output_count']}"
        )

    # Jitter bound check: every output ts within +/- jitter_minutes of *some*
    # original synthetic ts on the same minute grid. We verify the offset from
    # the nearest whole-minute grid point does not exceed the bound.
    bound_seconds = jitter_minutes * 60.0
    grid_base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    max_offset = 0.0
    for rec in out:
        ts = _parse_timestamp(rec["timestamp"])
        # Synthetic corpus events sit on an hourly grid; attribute each jittered
        # timestamp to its nearest whole hour (unambiguous since jitter < 30min).
        hours = round((ts - grid_base).total_seconds() / 3600.0)
        nearest = grid_base + dt.timedelta(hours=hours)
        offset = abs((ts - nearest).total_seconds())
        max_offset = max(max_offset, offset)
    # allow a tiny epsilon for float rendering
    if max_offset > bound_seconds + 1e-6:
        failures.append(
            f"jitter exceeded bound: max offset {max_offset:.3f}s > {bound_seconds:.3f}s"
        )

    # Duplicates keep identical source_ref: count refs, ensure exactly `dup`
    # extra copies beyond unique survivors.
    refs = [r["source_ref"] for r in out]
    extra = len(refs) - len(set(refs))
    if extra != expected_dup:
        failures.append(f"duplicate source_ref extras expected {expected_dup}, got {extra}")

    # Determinism: run again with same seed, compare sha256 of serialized output.
    out2, _ = degrade(
        corpus,
        drop_pct=drop_pct,
        dup_pct=dup_pct,
        jitter_minutes=jitter_minutes,
        truncate_pct=truncate_pct,
        seed=seed,
    )
    ser1 = "\n".join(json.dumps(r, sort_keys=True) for r in out)
    ser2 = "\n".join(json.dumps(r, sort_keys=True) for r in out2)
    h1 = hashlib.sha256(ser1.encode()).hexdigest()
    h2 = hashlib.sha256(ser2.encode()).hexdigest()
    if h1 != h2:
        failures.append(f"determinism failed: {h1[:12]} != {h2[:12]}")

    print(f"[verify] jitter max offset : {max_offset:.3f}s (bound {bound_seconds:.1f}s)")
    print(f"[verify] output sha256     : {h1}")
    print(f"[verify] determinism sha256: {h2}")

    if failures:
        print("FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Apply degraded-input transforms to a JSONL corpus."
    )
    p.add_argument("--corpus", help="Input JSONL corpus path")
    p.add_argument("--out", help="Output JSONL path")
    p.add_argument("--drop-pct", type=float, default=0.0, help="Percent of events to drop")
    p.add_argument("--dup-pct", type=float, default=0.0, help="Percent of survivors to duplicate")
    p.add_argument(
        "--jitter-minutes", type=float, default=0.0, help="Bound (+/-) for timestamp jitter"
    )
    p.add_argument(
        "--truncate-pct", type=float, default=0.0, help="Percent of events whose content is truncated"
    )
    p.add_argument("--seed", type=int, default=0, help="RNG seed for determinism")
    p.add_argument(
        "--verify",
        action="store_true",
        help="Run internal self-check on a synthetic corpus and print PASS/FAIL",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.verify:
        return _run_verify()

    if not args.corpus or not args.out:
        print("error: --corpus and --out are required unless --verify is set", file=sys.stderr)
        return 2

    records = _read_jsonl(args.corpus)
    out, manifest = degrade(
        records,
        drop_pct=args.drop_pct,
        dup_pct=args.dup_pct,
        jitter_minutes=args.jitter_minutes,
        truncate_pct=args.truncate_pct,
        seed=args.seed,
    )
    _write_jsonl(args.out, out)
    _print_manifest(manifest)
    print(f"wrote {len(out)} lines -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
