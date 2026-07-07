#!/usr/bin/env python3
"""Negative-control corpus transforms (EVL-06).

Generate falsification corpora from an event JSONL corpus:

  * ``shuffle-time``: permute the ``event_timestamp`` values across all lines,
    then re-sort the lines by their new timestamp. This destroys any real
    temporal relationship between an event and its content/entities while
    keeping the multiset of timestamps intact.
  * ``permute-entities``: permute the ``entity_refs`` lists across lines,
    leaving the content strings untouched. This destroys any real association
    between an event and the entities it references.
  * ``both``: apply ``shuffle-time`` first, then ``permute-entities``.

All transforms are deterministic under ``--seed`` (via ``random.Random(seed)``)
so re-running with the same seed produces a byte-identical output file.

Acceptance guarantees (see ``--verify``):
  * output line count == input line count
  * multiset of ``event_timestamp`` values preserved
  * multiset of ``entity_refs`` lists preserved
  * same seed => identical output file (sha256 match)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import tempfile
from collections import Counter
from typing import Any, Dict, List, Optional


TIMESTAMP_KEY = "event_timestamp"
ENTITY_KEY = "entity_refs"


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def read_corpus(path: str) -> List[Dict[str, Any]]:
    """Read a JSONL corpus into a list of dicts (blank lines skipped)."""
    records: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def write_corpus(path: str, records: List[Dict[str, Any]]) -> None:
    """Write records as JSONL.

    ``sort_keys=True`` and a fixed separator make the serialization canonical
    so that identical record content always yields identical bytes.
    """
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True, ensure_ascii=False))
            fh.write("\n")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Multiset helpers (for verification)
# ---------------------------------------------------------------------------

def _timestamp_multiset(records: List[Dict[str, Any]]) -> Counter:
    return Counter(
        json.dumps(r.get(TIMESTAMP_KEY), sort_keys=True) for r in records
    )


def _entity_multiset(records: List[Dict[str, Any]]) -> Counter:
    return Counter(
        json.dumps(r.get(ENTITY_KEY), sort_keys=True) for r in records
    )


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------

def shuffle_time(
    records: List[Dict[str, Any]], rng: random.Random
) -> List[Dict[str, Any]]:
    """Permute ``event_timestamp`` values across lines, then re-sort by them.

    A deep-ish copy is made (top-level dict copied) so the input list is not
    mutated. The timestamp *values* are shuffled and reassigned; then the whole
    list is re-sorted by the new timestamp so output ordering follows time.
    """
    out = [dict(r) for r in records]
    timestamps = [r.get(TIMESTAMP_KEY) for r in out]

    order = list(range(len(timestamps)))
    rng.shuffle(order)
    permuted = [timestamps[i] for i in order]

    for rec, ts in zip(out, permuted):
        rec[TIMESTAMP_KEY] = ts

    # Re-sort by the new timestamp. Timestamps may be heterogeneous, so key on
    # a canonical JSON string to guarantee a total, deterministic ordering.
    out.sort(key=lambda r: json.dumps(r.get(TIMESTAMP_KEY), sort_keys=True))
    return out


def permute_entities(
    records: List[Dict[str, Any]], rng: random.Random
) -> List[Dict[str, Any]]:
    """Permute the ``entity_refs`` lists across lines; content untouched."""
    out = [dict(r) for r in records]
    entity_lists = [r.get(ENTITY_KEY) for r in out]

    order = list(range(len(entity_lists)))
    rng.shuffle(order)
    permuted = [entity_lists[i] for i in order]

    for rec, ents in zip(out, permuted):
        rec[ENTITY_KEY] = ents
    return out


def apply_mode(
    records: List[Dict[str, Any]], mode: str, seed: int
) -> List[Dict[str, Any]]:
    """Apply the requested transform(s) deterministically under ``seed``."""
    rng = random.Random(seed)
    if mode == "shuffle-time":
        return shuffle_time(records, rng)
    if mode == "permute-entities":
        return permute_entities(records, rng)
    if mode == "both":
        stage1 = shuffle_time(records, rng)
        return permute_entities(stage1, rng)
    raise ValueError(f"unknown mode: {mode!r}")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def _synthetic_corpus(n: int = 12) -> List[Dict[str, Any]]:
    """Build a small deterministic synthetic corpus for self-checks."""
    records = []
    for i in range(n):
        records.append(
            {
                "event_id": f"evt-{i:03d}",
                "event_timestamp": f"2026-07-06T00:{i:02d}:00Z",
                "entity_refs": [f"host-{i}", f"iface-{i % 4}"],
                "content": f"synthetic event number {i}",
            }
        )
    return records


def _check_transform(records: List[Dict[str, Any]], mode: str, seed: int) -> bool:
    """Return True if line-count and both multisets are preserved for ``mode``."""
    in_ts = _timestamp_multiset(records)
    in_ent = _entity_multiset(records)

    out = apply_mode(records, mode, seed)

    ok = True
    if len(out) != len(records):
        print(f"  [{mode}] FAIL line count: in={len(records)} out={len(out)}")
        ok = False
    if _timestamp_multiset(out) != in_ts:
        print(f"  [{mode}] FAIL timestamp multiset not preserved")
        ok = False
    if _entity_multiset(out) != in_ent:
        print(f"  [{mode}] FAIL entity_refs multiset not preserved")
        ok = False

    if ok:
        print(f"  [{mode}] line-count + multisets preserved (n={len(out)})")
    return ok


def _check_determinism(records: List[Dict[str, Any]], mode: str, seed: int) -> bool:
    """Return True if two same-seed runs produce sha256-identical output files."""
    tmpdir = tempfile.mkdtemp(prefix="negctl_verify_")
    p1 = os.path.join(tmpdir, f"{mode}_a.jsonl")
    p2 = os.path.join(tmpdir, f"{mode}_b.jsonl")
    write_corpus(p1, apply_mode(records, mode, seed))
    write_corpus(p2, apply_mode(records, mode, seed))
    h1, h2 = sha256_file(p1), sha256_file(p2)
    ok = h1 == h2
    status = "match" if ok else "MISMATCH"
    print(f"  [{mode}] same-seed determinism sha256 {status}: {h1[:16]}")
    return ok


def run_verify(seed: int) -> int:
    """Self-check on a generated corpus. Returns process exit code."""
    records = _synthetic_corpus()
    print(f"[verify] synthetic corpus lines: {len(records)} | seed={seed}")
    all_ok = True
    for mode in ("shuffle-time", "permute-entities", "both"):
        all_ok &= _check_transform(records, mode, seed)
        all_ok &= _check_determinism(records, mode, seed)
    print("PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Negative-control corpus transforms (EVL-06)."
    )
    p.add_argument("--corpus", help="input JSONL corpus path")
    p.add_argument(
        "--mode",
        choices=["shuffle-time", "permute-entities", "both"],
        help="transform to apply",
    )
    p.add_argument("--seed", type=int, default=42, help="RNG seed (default 42)")
    p.add_argument("--out", help="output JSONL path")
    p.add_argument(
        "--verify",
        action="store_true",
        help="run self-check on a generated corpus and print PASS/FAIL",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.verify:
        return run_verify(args.seed)

    missing = [n for n in ("corpus", "mode", "out") if getattr(args, n) is None]
    if missing:
        print(
            "error: --" + ", --".join(missing) + " required (or use --verify)",
            file=sys.stderr,
        )
        return 2

    records = read_corpus(args.corpus)
    out = apply_mode(records, args.mode, args.seed)
    write_corpus(args.out, out)
    print(
        f"wrote {len(out)} lines to {args.out} "
        f"(mode={args.mode}, seed={args.seed})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
