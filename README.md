# Pedkai - AI-Native Telco Operating System

Decision intelligence and automation for large-scale telcos.

## Quick Start

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the API server
uvicorn backend.app.main:app --reload
```

## Project Structure

```
Pedkai/
├── backend/           # FastAPI backend service
│   ├── app/
│   │   ├── api/       # REST endpoints
│   │   ├── core/      # Config, auth, database
│   │   ├── models/    # Pydantic schemas (incl. BSS ORM)
│   │   └── services/  # Business logic (incl. Policy Engine)
│   └── tests/
├── decision_memory/   # Context Graph (Decision Traces)
├── data_fabric/       # Data ingestion layer
├── anops/             # ANOps use case logic
└── frontend/          # Next.js dashboard
```

## Tech Stack

- **Backend**: Python 3.11+, FastAPI
- **Database**: PostgreSQL (TimescaleDB) with JSONB + pgvector
- **Streaming**: Apache Kafka
- **Intelligence**: Gemini AI + Declarative Policy Engine (YAML)
- **Financial Context**: BSS Data Layer (Revenue & Billing)
- **Frontend**: Next.js

## Operational Constraints

- **Artifact Synchronization**: All key project artifacts (`task.md`, `walkthrough.md`, `implementation_plan_consolidated.md`, etc.) must be updated directly in the project root. Internal "brain" copies must be synchronized to the root after every major update.

## License

Proprietary - All rights reserved
