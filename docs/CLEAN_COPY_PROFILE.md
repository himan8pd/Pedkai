# Clean Copy Profile

This profile defines what is considered a useful, shippable copy of this repository.

## Included

- Runtime/backend code: `backend/`
- Frontend source: `frontend/` (excluding generated build artifacts)
- Tests: `tests/`
- Operational scripts: `scripts/`, startup and run shell scripts in repo root
- Infra and deployment assets: `docker-compose*.yml`, `Dockerfile*`, `Caddyfile`, `k8s/`, `.github/`
- Configuration and dependency files: `requirements*.txt`, `package.json`, `package-lock.json`, `.env.example`, `.env.cloud.example`, `pytest.ini`
- Core docs/specs:
  - `README.md`
  - `PRODUCT_SPEC.md`
  - `PRODUCT_SPEC_INTERNAL.md`
  - `PRODUCT_SPEC_EXTERNAL.md`
  - `docs/` (with `docs/archive` removed in clean copy)

## Excluded

- VCS metadata and local environments: `.git/`, `venv/`, `.venv/`
- Generated artifacts and caches:
  - `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`
  - `frontend/node_modules/`, `frontend/.next/`, `frontend/out/`, `frontend/tsconfig.tsbuildinfo`
- Root-level ad hoc notes, temporary reports, duplicate markdown/text snapshots, and media assets not required for runtime or key docs

## Usage

Run from repository root:

```bash
chmod +x scripts/create_clean_copy.sh
./scripts/create_clean_copy.sh
```

Optional custom destination:

```bash
./scripts/create_clean_copy.sh ../Pedkai-clean
```

After export, inspect `CLEAN_COPY_MANIFEST.txt` in the output directory.
