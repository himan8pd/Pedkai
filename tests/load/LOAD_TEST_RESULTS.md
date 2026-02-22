# Pedkai Load Test Results

**Target**: 200,000 alarms/day (~2.3 alarms/second sustained)  
**Success criteria**: p95 < 500ms | p99 < 2s | error rate < 0.1%

---

## How to Run

```bash
cd /Users/himanshu/Projects/Pedkai

# Ensure backend is running
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 &

# Run load test (200K/day = 50 users, 2.3 RPS sustained, 5 min)
locust -f tests/load/locustfile.py \
  --headless -u 50 -r 5 --run-time 5m \
  --host http://localhost:8000 \
  --html tests/load/results_$(date +%Y%m%d).html
```

---

## Results

> **Status**: Pending — run the command above and paste results here.

| Endpoint | p50 | p95 | p99 | Error Rate | Pass? |
|----------|-----|-----|-----|-----------|-------|
| `GET /tmf-api/alarmManagement/v4/alarm` | — | — | — | — | ⏳ |
| `GET /api/v1/service-impact/clusters` | — | — | — | — | ⏳ |
| `GET /api/v1/stream/alarms` (SSE connect) | — | — | — | — | ⏳ |
| `POST /api/v1/auth/token` | — | — | — | — | ⏳ |
| `GET /api/v1/autonomous/scorecard` | — | — | — | — | ⏳ |

---

## Notes

- Test was run with SQLite in dev mode; production PostgreSQL will have better concurrent write performance
- SSE connections are long-lived — measure connection establishment time, not stream duration
- Results should be re-run against a PostgreSQL instance before pilot approval
