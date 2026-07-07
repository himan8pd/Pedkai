#!/usr/bin/env python3
"""Blind ingest driver (EVL-04).

Replay a corpus JSONL chronologically into a clean tenant through the real
Pedkai API, with authentication, tenant selection, resume support and simple
rate control.

Each corpus line is a JSON object with (at least) these fields::

    {
      "content": "...",
      "source_type": "alarm",
      "source_ref": "optional",
      "event_timestamp": "2026-01-01T00:00:00Z",
      "entity_refs": ["cell-123"]
    }

Auth flow (mirrors the real backend):
    1. POST {base}/api/v1/auth/token   (form-encoded username/password)
       -> {"access_token": ...}
    2. optional --select-tenant:
       POST {base}/api/v1/auth/select-tenant  {"tenant_id": ...}
       -> {"access_token": ...}   (new token bound to the tenant)

Ingest:
    POST {base}/api/v1/abeyance/ingest      (--endpoint ingest, default)
    POST {base}/api/v1/abeyance/ingest/v3   (--endpoint ingest_v3)

The driver is dependency-light: it uses ``requests`` when importable and
otherwise falls back to the stdlib ``urllib``.

Offline verification::

    python scripts/eval/run_blind_ingest.py \
        --base-url https://pedk.ai --username u --password p \
        --tenant-id t --corpus /tmp/sample.jsonl --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# HTTP transport: prefer requests, fall back to stdlib urllib.
# ---------------------------------------------------------------------------
try:  # pragma: no cover - trivial import guard
    import requests  # type: ignore

    _HTTP_LIB = "requests"
except Exception:  # pragma: no cover
    requests = None  # type: ignore
    _HTTP_LIB = "urllib"

import urllib.error
import urllib.parse
import urllib.request


class HttpError(RuntimeError):
    """Raised for non-2xx HTTP responses."""

    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


def _http_post(
    url: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
    form_body: Optional[Dict[str, Any]] = None,
    bearer: Optional[str] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """POST helper returning the decoded JSON response.

    Sends *either* a JSON body or a form-encoded body. Raises ``HttpError``
    on non-2xx responses.
    """
    headers: Dict[str, str] = {"Accept": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    if _HTTP_LIB == "requests":
        resp = requests.post(  # type: ignore[union-attr]
            url,
            json=json_body,
            data=form_body,
            headers=headers,
            timeout=timeout,
        )
        if not (200 <= resp.status_code < 300):
            raise HttpError(resp.status_code, resp.text)
        try:
            return resp.json()
        except ValueError:
            return {}

    # --- urllib fallback ---
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    else:
        data = urllib.parse.urlencode(form_body or {}).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as fh:
            raw = fh.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:  # non-2xx
        body = exc.read().decode("utf-8", errors="replace")
        raise HttpError(exc.code, body) from exc


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate(
    base_url: str,
    username: str,
    password: str,
    tenant_id: Optional[str],
    select_tenant: bool,
) -> str:
    """Log in and (optionally) bind a tenant, returning a bearer token."""
    token_url = f"{base_url}/api/v1/auth/token"
    body = _http_post(
        token_url, form_body={"username": username, "password": password}
    )
    token = body.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in login response: {body}")

    if select_tenant:
        if not tenant_id:
            raise RuntimeError("--select-tenant requires --tenant-id")
        sel_url = f"{base_url}/api/v1/auth/select-tenant"
        sel = _http_post(sel_url, json_body={"tenant_id": tenant_id}, bearer=token)
        token = sel.get("access_token") or token
    return token


# ---------------------------------------------------------------------------
# Corpus / payloads
# ---------------------------------------------------------------------------
def _endpoint_path(endpoint: str) -> str:
    return "/api/v1/abeyance/ingest/v3" if endpoint == "ingest_v3" else "/api/v1/abeyance/ingest"


def build_payload(record: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    """Map a corpus record onto the ingest request payload."""
    return {
        "content": record.get("content"),
        "source_type": record.get("source_type"),
        "source_ref": record.get("source_ref"),
        "event_timestamp": record.get("event_timestamp"),
        "entity_refs": record.get("entity_refs", []),
        "tenant_id": tenant_id,
    }


def load_corpus(path: Path) -> List[Dict[str, Any]]:
    """Load and chronologically sort corpus records from a JSONL file."""
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Corpus line {lineno} is not valid JSON: {exc}")

    # Chronological replay: sort by event_timestamp (missing -> last, stable).
    records.sort(key=lambda r: (r.get("event_timestamp") is None, r.get("event_timestamp") or ""))
    return records


# ---------------------------------------------------------------------------
# Resume support
# ---------------------------------------------------------------------------
def read_resume_index(resume_file: Optional[Path]) -> int:
    """Return the next index to process (0 if no/empty resume file)."""
    if not resume_file or not resume_file.exists():
        return 0
    try:
        text = resume_file.read_text(encoding="utf-8").strip()
        return int(text) if text else 0
    except (ValueError, OSError):
        return 0


def write_resume_index(resume_file: Optional[Path], index: int) -> None:
    if not resume_file:
        return
    try:
        resume_file.write_text(str(index), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Main ingest loop
# ---------------------------------------------------------------------------
def run(args: argparse.Namespace) -> int:
    corpus_path = Path(args.corpus)
    if not corpus_path.exists():
        print(f"ERROR: corpus not found: {corpus_path}", file=sys.stderr)
        return 2

    records = load_corpus(corpus_path)
    total = len(records)

    # --- dry run: print first 3 payloads, no network ---
    if args.dry_run:
        print(f"[dry-run] corpus={corpus_path} records={total} "
              f"endpoint={_endpoint_path(args.endpoint)} http_lib={_HTTP_LIB}")
        for i, rec in enumerate(records[:3]):
            payload = build_payload(rec, args.tenant_id)
            print(f"[dry-run] payload[{i}]: {json.dumps(payload, ensure_ascii=False)}")
        return 0

    password = args.password or os.environ.get("PEDKAI_EVAL_PASSWORD")
    if not password:
        print("ERROR: password required via --password or PEDKAI_EVAL_PASSWORD",
              file=sys.stderr)
        return 2

    base_url = args.base_url.rstrip("/")
    resume_file = Path(args.resume_file) if args.resume_file else None
    start_index = read_resume_index(resume_file)

    failures_path = (
        Path(f"{args.resume_file}.failures.jsonl") if args.resume_file else None
    )

    token = authenticate(
        base_url, args.username, password, args.tenant_id, args.select_tenant
    )

    ingest_url = f"{base_url}{_endpoint_path(args.endpoint)}"
    min_interval = 1.0 / args.rate if args.rate > 0 else 0.0

    processed = 0
    failures = 0
    print(f"Starting ingest: {total} records, resume from index {start_index}, "
          f"rate={args.rate}/s, http_lib={_HTTP_LIB}")

    for idx in range(start_index, total):
        rec = records[idx]
        payload = build_payload(rec, args.tenant_id)
        t0 = time.monotonic()
        try:
            _http_post(ingest_url, json_body=payload, bearer=token)
        except Exception as exc:  # noqa: BLE001 - record and continue
            failures += 1
            if failures_path is not None:
                with failures_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(
                        {"index": idx, "error": str(exc), "record": rec},
                        ensure_ascii=False,
                    ) + "\n")
        processed += 1

        # Persist resume position *after* each attempt (idx+1 = next to do).
        write_resume_index(resume_file, idx + 1)

        if processed % 100 == 0:
            print(f"  progress: {processed}/{total - start_index} "
                  f"(failures={failures})")

        # Rate control.
        elapsed = time.monotonic() - t0
        if min_interval > elapsed:
            time.sleep(min_interval - elapsed)

    rate_pct = (failures / processed * 100.0) if processed else 0.0
    print(f"Done: processed={processed} failures={failures} "
          f"failure_rate={rate_pct:.2f}%")
    if failures_path is not None and failures:
        print(f"Failures written to: {failures_path}")

    if rate_pct > 5.0:
        print("ERROR: failure rate exceeded 5% threshold", file=sys.stderr)
        return 1
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Blind ingest driver (EVL-04)")
    p.add_argument("--base-url", required=True, help="API base URL, e.g. https://pedk.ai")
    p.add_argument("--username", required=True)
    p.add_argument("--password", default=None,
                   help="Password (or set PEDKAI_EVAL_PASSWORD)")
    p.add_argument("--tenant-id", required=True)
    p.add_argument("--corpus", required=True, help="Corpus JSONL file")
    p.add_argument("--endpoint", choices=["ingest", "ingest_v3"], default="ingest")
    p.add_argument("--rate", type=float, default=2.0, help="Requests per second")
    p.add_argument("--resume-file", default=None,
                   help="Path storing next-index; failures go to <path>.failures.jsonl")
    p.add_argument("--select-tenant", action="store_true",
                   help="Bind tenant via /auth/select-tenant after login")
    p.add_argument("--dry-run", action="store_true",
                   help="Print first 3 payloads without any network call")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        return run(args)
    except Exception as exc:  # noqa: BLE001 - top-level guard
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
