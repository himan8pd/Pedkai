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
│   │   ├── models/    # Pydantic schemas
│   │   └── services/  # Business logic
│   └── tests/
├── decision_memory/   # Context Graph (Decision Traces)
├── data_fabric/       # Data ingestion layer
├── anops/             # ANOps use case logic
└── frontend/          # Next.js dashboard (future)
```

## Tech Stack

- **Backend**: Python 3.11+, FastAPI
- **Database**: PostgreSQL with JSONB + pgvector
- **Streaming**: Apache Kafka
- **LLM**: Gemini API
- **Frontend**: Next.js (planned)

## License

Proprietary - All rights reserved
