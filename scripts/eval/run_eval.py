#!/usr/bin/env python3
"""EVL-08 -- Blind-eval harness runner + markdown report.

One command that chains the eval pipeline end to end and emits a single
``eval_report.md`` capturing every metric plus run metadata:

    corpus build  (build_alarm_corpus.py)
      -> optional transform  (negative_controls.py / degrade_corpus.py)
      -> blind ingest        (run_blind_ingest.py)
      -> snap scoring        (score_snaps.py)          [clean + negative-control]
      -> divergence scoring  (divergence_score.py)     [optional, if inputs given]
      -> data completeness   (data_completeness.py)    [optional, if inputs given]
      -> eval_report.md

Design constraints (per the WBS):
  * The sibling eval scripts are invoked ONLY as subprocesses by path
    (``scripts/eval/<name>.py``). We NEVER import them, so each task stays
    independent.
  * ``--fake-inputs <dir>`` reads pre-made JSON metric files instead of running
    any child process. This makes the acceptance run fully deterministic with
    NO network, NO database and NO subprocesses -- ideal for CI smoke tests and
    for exercising the report renderer itself.

PASS/FAIL rule:
  A negative-control run (shuffle-time / permute-entities / degraded) SHOULD
  destroy the planted correlations, so its SNAP pair count must collapse. We
  FAIL the run when the negative-control snap-pair count exceeds a fraction
  (``--neg-control-threshold``, default 0.05 = 5%) of the clean-run snap-pair
  count. This is a falsification test: if a time/entity-scrambled corpus still
  snaps almost as many pairs as the real one, the engine is matching on
  something other than the planted signal.

Fake-inputs directory layout (all optional except the two score files):
    corpus_stats.json   -> build_alarm_corpus stats  {n_corpus, n_answers, ...}
    clean_score.json    -> score_snaps output for the clean run          (required)
    negctl_score.json   -> score_snaps output for the negative-control run (required)
    divergence.json     -> divergence_score output                       (optional)
    completeness.json   -> data_completeness output                      (optional)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Directory holding the sibling eval scripts (this file lives beside them).
EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent.parent


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _git_commit() -> str:
    """Return the current git commit hash, or '(unknown)' if unavailable."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
        )
        if out.returncode == 0:
            return out.stdout.strip() or "(unknown)"
    except Exception:  # noqa: BLE001 - metadata only, never fatal
        pass
    return "(unknown)"


def _load_json(path: Path) -> Optional[dict]:
    """Load a JSON file, returning None if it does not exist."""
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _fmt(value: Any) -> str:
    """Render a metric value for a markdown table cell."""
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


# --------------------------------------------------------------------------- #
# Markdown table renderers -- one per known scorer JSON shape.
# --------------------------------------------------------------------------- #

def _md_kv_table(title: str, rows: list[tuple[str, Any]]) -> str:
    lines = [f"### {title}", "", "| Metric | Value |", "| --- | --- |"]
    for key, val in rows:
        lines.append(f"| {key} | {_fmt(val)} |")
    lines.append("")
    return "\n".join(lines)


def _render_snap_score(title: str, score: Optional[dict]) -> str:
    """Render a score_snaps.py metrics dict as a markdown table."""
    if score is None:
        return f"### {title}\n\n_No data._\n"
    ordered_keys = [
        "tenant_id",
        "answer_groups_total",
        "true_pairs_total",
        "snap_pairs_total",
        "snap_pairs_correct",
        "near_miss_pairs_total",
        "retrieval_pairs_total",
        "candidates_evaluated_total",
        "pair_precision",
        "pair_recall",
        "near_miss_recall",
        "retrieval_recall",
    ]
    rows = [(k, score.get(k)) for k in ordered_keys if k in score]
    out = [_md_kv_table(title, rows)]

    tts = score.get("time_to_snap_seconds")
    if isinstance(tts, dict):
        tts_rows = [
            (k, tts.get(k))
            for k in ("count", "median", "p90", "p95", "p99", "min", "max")
        ]
        out.append(_md_kv_table(f"{title} -- time-to-snap (seconds)", tts_rows))
    return "\n".join(out)


def _render_divergence(score: Optional[dict]) -> str:
    """Render a divergence_score.py results dict as a per-type table."""
    if score is None:
        return ""
    header = (
        "### Divergence scoring (per type)\n\n"
        "| type | detected | truth | TP | precision | recall | "
        "unresolved_det | unresolved_truth |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |"
    )
    lines = [header]
    ordered = [
        "dark_node", "phantom_node", "dark_attribute", "identity_mutation",
        "dark_edge", "phantom_edge", "overall",
    ]
    seen = [t for t in ordered if t in score]
    for t in list(score.keys()):
        if t not in seen:
            seen.append(t)
    for t in seen:
        r = score[t]
        lines.append(
            f"| {t} | {_fmt(r.get('detected'))} | {_fmt(r.get('truth'))} | "
            f"{_fmt(r.get('tp'))} | {_fmt(r.get('precision'))} | "
            f"{_fmt(r.get('recall'))} | {_fmt(r.get('unresolved_detected'))} | "
            f"{_fmt(r.get('unresolved_truth'))} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_completeness(report: Optional[dict]) -> str:
    """Render a data_completeness.py report as overall + per-type tables."""
    if report is None:
        return ""
    out: list[str] = []
    overall = report.get("overall", {})
    out.append(_md_kv_table(
        "Data completeness -- overall",
        [
            ("total", overall.get("total")),
            ("with_alarm_signal", overall.get("with_alarm_signal")),
            ("with_kpi_signal", overall.get("with_kpi_signal")),
            ("with_any_signal", overall.get("with_any_signal")),
            ("coverage", overall.get("coverage")),
            ("kpi_included", overall.get("kpi_included")),
        ],
    ))

    per_type = report.get("per_entity_type", {})
    if per_type:
        lines = [
            "### Data completeness -- per entity_type",
            "",
            "| entity_type | total | alarm | kpi | any | coverage |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for etype, row in per_type.items():
            lines.append(
                f"| {etype} | {_fmt(row.get('total'))} | "
                f"{_fmt(row.get('with_alarm_signal'))} | "
                f"{_fmt(row.get('with_kpi_signal'))} | "
                f"{_fmt(row.get('with_any_signal'))} | "
                f"{_fmt(row.get('coverage'))} |"
            )
        lines.append("")
        out.append("\n".join(lines))
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# PASS/FAIL evaluation
# --------------------------------------------------------------------------- #

def evaluate_pass_fail(
    clean_score: Optional[dict],
    negctl_score: Optional[dict],
    threshold: float,
) -> dict:
    """Decide PASS/FAIL from clean vs negative-control snap-pair counts.

    FAIL if negative-control snap pair count > threshold * clean snap pair count.
    If either score is missing we cannot make the falsification call and report
    ``INCONCLUSIVE`` (treated as non-passing for CI safety).
    """
    if clean_score is None or negctl_score is None:
        return {
            "verdict": "INCONCLUSIVE",
            "reason": "clean and/or negative-control snap scores are missing",
            "clean_snap_pairs": clean_score.get("snap_pairs_total") if clean_score else None,
            "negctl_snap_pairs": negctl_score.get("snap_pairs_total") if negctl_score else None,
            "threshold": threshold,
            "limit": None,
        }

    clean_pairs = int(clean_score.get("snap_pairs_total", 0))
    negctl_pairs = int(negctl_score.get("snap_pairs_total", 0))
    limit = threshold * clean_pairs
    passed = negctl_pairs <= limit
    ratio = (negctl_pairs / clean_pairs) if clean_pairs else float("inf")
    return {
        "verdict": "PASS" if passed else "FAIL",
        "reason": (
            f"negative-control snap pairs ({negctl_pairs}) "
            f"{'<=' if passed else '>'} {threshold:.0%} of clean snap pairs "
            f"({clean_pairs}) [limit {limit:.1f}]"
        ),
        "clean_snap_pairs": clean_pairs,
        "negctl_snap_pairs": negctl_pairs,
        "ratio": ratio,
        "threshold": threshold,
        "limit": limit,
    }


# --------------------------------------------------------------------------- #
# Report assembly
# --------------------------------------------------------------------------- #

def build_report(
    *,
    args: argparse.Namespace,
    corpus_stats: Optional[dict],
    clean_score: Optional[dict],
    negctl_score: Optional[dict],
    divergence: Optional[dict],
    completeness: Optional[dict],
    verdict: dict,
    source: str,
) -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    commit = _git_commit()

    parts: list[str] = []
    parts.append("# Abeyance blind-eval report\n")

    # --- Run metadata ---
    meta_rows = [
        ("run_timestamp_utc", now),
        ("git_commit", commit),
        ("mode", args.mode),
        ("input_source", source),
        ("base_url", getattr(args, "base_url", None)),
        ("tenant_id", getattr(args, "tenant_id", None)),
        ("degrade_args", getattr(args, "degrade_args", None) or "(none)"),
        ("neg_control_threshold", args.neg_control_threshold),
    ]
    parts.append(_md_kv_table("Run metadata", meta_rows))

    # --- PASS/FAIL banner (prominent, near the top) ---
    parts.append(
        f"## RESULT: {verdict['verdict']}\n\n{verdict['reason']}\n"
    )

    # --- Corpus stats ---
    if corpus_stats is not None:
        parts.append(_md_kv_table(
            "Corpus stats",
            [
                ("corpus_events", corpus_stats.get("n_corpus")),
                ("answer_groups", corpus_stats.get("n_answers")),
                ("corpus_path", corpus_stats.get("out_corpus")),
                ("answers_path", corpus_stats.get("out_answers")),
            ],
        ))

    # --- Snap scores: clean + negative control ---
    parts.append("## Snap scoring\n")
    parts.append(_render_snap_score("Clean run", clean_score))
    parts.append(_render_snap_score(
        f"Negative-control run (mode={args.mode})", negctl_score
    ))

    # --- Optional divergence + completeness ---
    div_md = _render_divergence(divergence)
    if div_md:
        parts.append("## Topology divergence\n")
        parts.append(div_md)

    comp_md = _render_completeness(completeness)
    if comp_md:
        parts.append("## Data completeness\n")
        parts.append(comp_md)

    # --- Final machine-readable PASS/FAIL line (last line for easy grep) ---
    parts.append(
        f"PASS/FAIL: {verdict['verdict']} "
        f"(negctl_snap_pairs={verdict.get('negctl_snap_pairs')}, "
        f"clean_snap_pairs={verdict.get('clean_snap_pairs')}, "
        f"threshold={verdict['threshold']})\n"
    )

    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Live pipeline (subprocess orchestration)
# --------------------------------------------------------------------------- #

def _script(name: str) -> str:
    return str(EVAL_DIR / f"{name}.py")


def _run_child(argv: list[str]) -> None:
    """Run a sibling eval script as a subprocess; raise on non-zero exit."""
    print(f"[run_eval] $ {' '.join(argv)}", flush=True)
    result = subprocess.run(argv, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        raise RuntimeError(
            f"child exited {result.returncode}: {' '.join(argv)}"
        )


def run_live(args: argparse.Namespace, out_dir: Path) -> dict:
    """Execute the full pipeline via subprocesses and collect metric JSONs.

    Returns a dict of the loaded metric objects. This path requires --alarms,
    --base-url, --tenant-id, --dsn and a password (via env). It is intentionally
    NOT exercised by the deterministic acceptance test.
    """
    py = sys.executable
    corpus_path = out_dir / "corpus.jsonl"
    answers_path = out_dir / "answers.jsonl"

    # 1. Build corpus + answer key.
    _run_child([
        py, _script("build_alarm_corpus"),
        "--alarms", args.alarms,
        "--out-corpus", str(corpus_path),
        "--out-answers", str(answers_path),
    ])
    corpus_stats = {
        "n_corpus": sum(1 for _ in corpus_path.open(encoding="utf-8")),
        "n_answers": sum(1 for _ in answers_path.open(encoding="utf-8")),
        "out_corpus": str(corpus_path),
        "out_answers": str(answers_path),
    }

    # 2. Optional transform for the negative-control corpus.
    negctl_corpus = out_dir / "corpus_negctl.jsonl"
    if args.mode == "clean":
        # No transform: negative control == clean (verdict will be INCONCLUSIVE
        # in spirit, but we still score both against the same corpus).
        negctl_corpus = corpus_path
    elif args.mode in ("shuffle-time", "permute-entities"):
        _run_child([
            py, _script("negative_controls"),
            "--corpus", str(corpus_path),
            "--mode", args.mode,
            "--out", str(negctl_corpus),
        ])
    elif args.mode == "degraded":
        degrade_argv = [
            py, _script("degrade_corpus"),
            "--corpus", str(corpus_path),
            "--out", str(negctl_corpus),
        ]
        if args.degrade_args:
            degrade_argv.extend(args.degrade_args.split())
        _run_child(degrade_argv)

    # 3. Ingest clean + negative-control corpora into separate tenants.
    clean_tenant = args.tenant_id
    negctl_tenant = f"{args.tenant_id}_negctl"
    _run_child([
        py, _script("run_blind_ingest"),
        "--base-url", args.base_url,
        "--username", args.username,
        "--tenant-id", clean_tenant,
        "--corpus", str(corpus_path),
        "--select-tenant",
    ])
    clean_score_path = out_dir / "clean_score.json"
    _run_child([
        py, _script("score_snaps"),
        "--dsn", args.dsn,
        "--tenant-id", clean_tenant,
        "--answers", str(answers_path),
        "--out", str(clean_score_path),
    ])
    clean_score = _load_json(clean_score_path)

    negctl_score = None
    if args.mode != "clean":
        _run_child([
            py, _script("run_blind_ingest"),
            "--base-url", args.base_url,
            "--username", args.username,
            "--tenant-id", negctl_tenant,
            "--corpus", str(negctl_corpus),
            "--select-tenant",
        ])
        negctl_score_path = out_dir / "negctl_score.json"
        _run_child([
            py, _script("score_snaps"),
            "--dsn", args.dsn,
            "--tenant-id", negctl_tenant,
            "--answers", str(answers_path),
            "--out", str(negctl_score_path),
        ])
        negctl_score = _load_json(negctl_score_path)

    return {
        "corpus_stats": corpus_stats,
        "clean_score": clean_score,
        "negctl_score": negctl_score,
        "divergence": None,
        "completeness": None,
    }


# --------------------------------------------------------------------------- #
# Fake-inputs pipeline (no children, deterministic)
# --------------------------------------------------------------------------- #

def run_fake(fake_dir: Path) -> dict:
    """Load pre-made metric JSONs -- no network, no DB, no subprocesses."""
    clean = _load_json(fake_dir / "clean_score.json")
    negctl = _load_json(fake_dir / "negctl_score.json")
    if clean is None or negctl is None:
        raise SystemExit(
            f"--fake-inputs {fake_dir}: require clean_score.json and "
            f"negctl_score.json"
        )
    return {
        "corpus_stats": _load_json(fake_dir / "corpus_stats.json"),
        "clean_score": clean,
        "negctl_score": negctl,
        "divergence": _load_json(fake_dir / "divergence.json"),
        "completeness": _load_json(fake_dir / "completeness.json"),
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="EVL-08 blind-eval harness runner + markdown report.",
    )
    # Passthrough / live-mode flags.
    p.add_argument("--alarms", help="events_alarms.parquet (live corpus build)")
    p.add_argument("--base-url", help="API base URL for ingest")
    p.add_argument("--username", default="pedkai_admin", help="ingest username")
    p.add_argument("--tenant-id", help="tenant id to ingest/score")
    p.add_argument(
        "--mode",
        choices=["clean", "shuffle-time", "permute-entities", "degraded"],
        default="clean",
        help="negative-control transform applied to the eval corpus",
    )
    p.add_argument("--degrade-args", default=None,
                   help="extra args passed through to degrade_corpus.py (quoted)")
    p.add_argument("--dsn", help="SQLAlchemy DSN for score_snaps")
    p.add_argument("--out-dir", required=True, help="output directory")

    # Report / verdict tuning.
    p.add_argument("--neg-control-threshold", type=float, default=0.05,
                   help="FAIL if negctl snap pairs > this fraction of clean "
                        "(default 0.05 = 5%%)")

    # Deterministic self-test.
    p.add_argument("--fake-inputs", default=None,
                   help="read pre-made metric JSONs from this dir instead of "
                        "running any child process")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.fake_inputs:
        data = run_fake(Path(args.fake_inputs))
        source = f"fake-inputs:{args.fake_inputs}"
    else:
        missing = [
            f for f, v in (
                ("--alarms", args.alarms),
                ("--base-url", args.base_url),
                ("--tenant-id", args.tenant_id),
                ("--dsn", args.dsn),
            ) if not v
        ]
        if missing:
            print(
                "error: live mode requires " + ", ".join(missing)
                + " (or pass --fake-inputs <dir>)",
                file=sys.stderr,
            )
            return 2
        data = run_live(args, out_dir)
        source = "live-pipeline"

    verdict = evaluate_pass_fail(
        data["clean_score"], data["negctl_score"], args.neg_control_threshold
    )

    report_md = build_report(
        args=args,
        corpus_stats=data["corpus_stats"],
        clean_score=data["clean_score"],
        negctl_score=data["negctl_score"],
        divergence=data["divergence"],
        completeness=data["completeness"],
        verdict=verdict,
        source=source,
    )

    report_path = out_dir / "eval_report.md"
    report_path.write_text(report_md, encoding="utf-8")
    print(f"[run_eval] wrote {report_path}")
    print(f"[run_eval] verdict: {verdict['verdict']} -- {verdict['reason']}")

    # Exit non-zero on FAIL so CI can gate on it; PASS/INCONCLUSIVE differ.
    return 0 if verdict["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
