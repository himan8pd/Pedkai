# Pedkai - AI-Native Telco Operating System

Pedkai is a telco decision intelligence platform with a FastAPI backend, a Next.js dashboard, policy-driven automation, and optional Kafka/data replay workflows.

## What Is In This Repo

- **Backend API**: `backend/app/main.py` (FastAPI)
- **Frontend**: `frontend/` (Next.js 16 + React 19)
- **Infra (local dev)**: `docker-compose.yml` (PostgreSQL + TimescaleDB + Kafka + Kafka UI)
- **Infra (cloud app VM)**: `docker-compose.cloud.yml` (backend + frontend static build + Kafka + Ollama + replay worker)
- **Automation scripts**:
	- `startup_local.sh`: local demo mode with SQLite
	- `startup_prod.sh`: production-like mode with Docker infra + Alembic migrations
	- `startup.sh`: unified local startup (backend + frontend with health verification)
	- `run_demo.sh`: backend-only demo start
	- `run_frontend.sh`: frontend-only dev start

## Prerequisites

- Python 3.11+
- Node.js + npm (for `frontend/`)
- Docker Desktop (for `startup_prod.sh` and compose-based infra)

## Environment Configuration

For local development:

```bash
cp .env.example .env
```

For cloud deployment reference:

```bash
cp .env.cloud.example .env
```

Important notes:

- `startup_local.sh` forces SQLite DB URLs and does not require Docker.
- `startup_prod.sh` expects a valid `.env` and Docker running.
- Backend defaults:
	- API: `http://localhost:8000`
	- Swagger docs: `http://localhost:8000/docs`
- Frontend default: `http://localhost:3000`

## Quick Start (Recommended)

### 1) Install Python dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 2) Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

### 3) Start in local/demo mode (SQLite, no Docker)

```bash
./startup_local.sh
```

This starts:

- Backend on `PEDKAI_BACKEND_PORT` (default `8000`)
- Frontend on `PEDKAI_FRONTEND_PORT` (default `3000`)
- Connectivity checks against `/health` and frontend root URL

## Other Run Modes

### Unified startup (local)

```bash
./startup.sh
```

### Production-like startup (Docker infra + migrations + app)

```bash
./startup_prod.sh
```

What `startup_prod.sh` does:

1. Verifies Docker and `.env`
2. Starts `postgres`, `timescaledb`, and `kafka` via `docker compose`
3. Runs Alembic migrations (`backend/alembic.ini`)
4. Launches backend and frontend
5. Verifies service health

### Backend only

```bash
./run_demo.sh
```

### Frontend only

```bash
./run_frontend.sh
```

### Manual backend run

```bash
source venv/bin/activate
python -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

## Docker Compose (Local Infra)

`docker-compose.yml` includes:

- PostgreSQL with pgvector on `5432`
- TimescaleDB on `5433`
- Kafka on `9092`
- Kafka UI on `8080`

Bring infra up/down manually if needed:

```bash
docker compose up -d
docker compose down
```

## Testing

Pytest is configured via `pytest.ini` (`testpaths = tests`).

Run all tests:

```bash
source venv/bin/activate
pytest
```

Run a specific test file:

```bash
pytest tests/test_e2e_shadow_mode.py
```

## Frontend Commands

From `frontend/`:

```bash
npm run dev
npm run build
npm run start
npm run lint
```

## Project Layout (High-Level)

```text
Pedkai/
|- backend/            FastAPI service, Alembic migrations, domain logic
|- frontend/           Next.js dashboard
|- tests/              Pytest suites (unit, integration, validation, load, security)
|- data_fabric/        Data ingestion and processing utilities
|- decision_memory/    Decision/context memory components
|- anops/              ANOps use-case implementation assets
|- scripts/            Operational and utility scripts
|- docs/               Architecture and implementation documentation
|- docker-compose.yml
|- docker-compose.cloud.yml
|- startup_local.sh
|- startup_prod.sh
|- startup.sh
```

## Key Docs

- `PRODUCT_SPEC.md`
- `PRODUCT_SPEC_INTERNAL.md`
- `PRODUCT_SPEC_EXTERNAL.md`
- `README.md` (this file)
- `IMPLEMENTATION_PLAN_T025.md`
- `WALKTHROUGH_T025.md`

## License

Proprietary - All rights reserved.
