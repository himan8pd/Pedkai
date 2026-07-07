#!/usr/bin/env python3
"""EVL-03 — Alarm blind-eval corpus builder.

Converts an ``events_alarms.parquet`` file into:

  (a) a chronologically sorted JSONL of ingest payloads (``--out-corpus``), and
  (b) an answer-key JSONL of correlation groups (``--out-answers``).

CRITICAL: rows whose ``correlation_group_id`` is NULL / NaN / empty are
uncorrelated alarms and MUST be excluded before grouping. Grouping with
``dropna=False`` bundles all of them into a spurious extra group.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import pandas as pd


def _iso(ts: Any) -> str:
    """Render a pandas Timestamp as an ISO-8601 string."""
    return pd.Timestamp(ts).isoformat()


def _clean_str(value: Any) -> str:
    """Coerce a possibly-null value to a stripped string ('' if null)."""
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    if value is pd.NaT:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def build(
    alarms_path: str,
    out_corpus: str,
    out_answers: str,
    limit: int = 0,
) -> dict[str, Any]:
    df = pd.read_parquet(alarms_path)

    if limit and limit > 0:
        df = df.head(limit)

    # --- Corpus (sorted ASCENDING by raised_at) ---------------------------
    corpus_df = df.sort_values("raised_at", kind="mergesort").reset_index(drop=True)

    corpus_alarm_ids: set[str] = set()
    n_corpus = 0
    with open(out_corpus, "w", encoding="utf-8") as fh:
        for row in corpus_df.itertuples(index=False):
            additional_text = _clean_str(getattr(row, "additional_text"))
            probable_cause = _clean_str(getattr(row, "probable_cause"))
            alarm_type = _clean_str(getattr(row, "alarm_type"))
            severity = _clean_str(getattr(row, "severity"))
            alarm_id = _clean_str(getattr(row, "alarm_id"))
            entity_id = _clean_str(getattr(row, "entity_id"))

            content = (
                additional_text
                + " Probable cause: "
                + probable_cause
                + " ["
                + alarm_type
                + "/"
                + severity
                + "]"
            )
            payload = {
                "content": content,
                "source_type": "ALARM",
                "source_ref": alarm_id,
                "event_timestamp": _iso(getattr(row, "raised_at")),
                "entity_refs": [entity_id],
                "alarm_id": alarm_id,
            }
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
            corpus_alarm_ids.add(alarm_id)
            n_corpus += 1

    # --- Answer key (correlation groups, size >= 2) -----------------------
    # EXCLUDE null / NaN / empty correlation_group_id BEFORE grouping.
    grp = df.dropna(subset=["correlation_group_id"]).copy()
    grp["correlation_group_id"] = grp["correlation_group_id"].astype(str).str.strip()
    grp = grp[grp["correlation_group_id"] != ""]

    n_answers = 0
    with open(out_answers, "w", encoding="utf-8") as fh:
        for group_id, sub in grp.groupby("correlation_group_id", sort=True):
            if len(sub) < 2:
                continue
            raised = sub["raised_at"]
            span_seconds = (raised.max() - raised.min()).total_seconds()
            domains = sorted({_clean_str(d) for d in sub["domain"].tolist()})
            record = {
                "group_id": str(group_id),
                "alarm_ids": [_clean_str(a) for a in sub["alarm_id"].tolist()],
                "domains": domains,
                "span_seconds": span_seconds,
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            n_answers += 1

    return {
        "n_corpus": n_corpus,
        "n_answers": n_answers,
        "corpus_alarm_ids": corpus_alarm_ids,
        "out_corpus": out_corpus,
        "out_answers": out_answers,
    }


def verify(out_corpus: str, out_answers: str, corpus_alarm_ids: set[str]) -> bool:
    ok = True

    # 1. Corpus line count + strict time ordering.
    prev = None
    n_corpus = 0
    ordered = True
    with open(out_corpus, "r", encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            ts = pd.Timestamp(rec["event_timestamp"])
            if prev is not None and ts < prev:
                ordered = False
            prev = ts
            n_corpus += 1
    print(f"[verify] corpus lines: {n_corpus} (expected 15695)")
    print(f"[verify] corpus time-ordered (ascending): {ordered}")
    ok = ok and (n_corpus == 15695) and ordered

    # 2. Answer group count + every alarm_id present in corpus.
    n_answers = 0
    all_present = True
    all_size_ge_2 = True
    with open(out_answers, "r", encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            n_answers += 1
            if len(rec["alarm_ids"]) < 2:
                all_size_ge_2 = False
            for aid in rec["alarm_ids"]:
                if aid not in corpus_alarm_ids:
                    all_present = False
    print(f"[verify] answer groups: {n_answers} (expected 5865, NOT 5866)")
    print(f"[verify] all groups size >= 2: {all_size_ge_2}")
    print(f"[verify] all answer alarm_ids present in corpus: {all_present}")
    ok = ok and (n_answers == 5865) and all_present and all_size_ge_2

    print(f"[verify] ALL CHECKS PASSED: {ok}")
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Alarm blind-eval corpus builder")
    parser.add_argument("--alarms", required=True, help="Path to events_alarms.parquet")
    parser.add_argument("--out-corpus", required=True, help="Output corpus JSONL path")
    parser.add_argument("--out-answers", required=True, help="Output answer-key JSONL path")
    parser.add_argument("--limit", type=int, default=0, help="Row limit (0 = all)")
    parser.add_argument("--verify", action="store_true", help="Run acceptance checks")
    args = parser.parse_args(argv)

    result = build(args.alarms, args.out_corpus, args.out_answers, args.limit)
    print(f"Wrote corpus: {result['out_corpus']} ({result['n_corpus']} lines)")
    print(f"Wrote answers: {result['out_answers']} ({result['n_answers']} groups)")

    if args.verify:
        ok = verify(args.out_corpus, args.out_answers, result["corpus_alarm_ids"])
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
