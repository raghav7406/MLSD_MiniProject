# Health Insurance Pre-Authorisation Desk – Runbook

## Service Map

| Service | Port | Purpose |
|---|---|---|
| API (`app`) | 8000 | FastAPI REST endpoints, metrics |
| Worker | — | Celery task executor |
| Redis | 6379 | Broker and result backend |
| Prometheus | 9090 | Metrics scraping |
| Grafana | 3000 | Dashboards |

---

## 1. Start from Clean Clone

```powershell
# 1. Clone and enter the repo
git clone <repo-url>
cd MLSD_MiniProject

# 2. Copy env file (no secrets needed for local/deterministic mode)
copy .env.example .env

# 3. Start everything
docker compose up --build

# 4. Verify health
Invoke-RestMethod http://localhost:8000/health
```

Expected response:
```json
{"status": "healthy", "circuit_breaker": "CLOSED", ...}
```

---

## 2. Local Development (No Docker)

```powershell
# Install dependencies
pip install -r requirements.txt

# Ingest corpus
python -m src.ingestion.ingest_pipeline --force

# Start API (local mode, no Celery)
uvicorn src.services.api:app --reload --host 0.0.0.0 --port 8000

# In another terminal: start Streamlit client
streamlit run src/client/app.py
```

---

## 3. Health Checks

```powershell
# API health
Invoke-RestMethod http://localhost:8000/health

# Prometheus metrics
Invoke-RestMethod http://localhost:8000/metrics

# Circuit breaker state (in health response)
# CLOSED = normal, OPEN = degraded, HALF_OPEN = recovering

# Grafana dashboard
# http://localhost:3000  (admin / admin)
```

---

## 4. Common Commands

### Submit a pre-auth request
```powershell
$body = @{
    member_id = "M-1001"; policy_number = "P-2001"
    policy_name = "Care Supreme"; diagnosis_name = "Cataract"
    procedure_name = "Phacoemulsification"; admission_type = "PLANNED"
    policy_tenure_months = 11; estimated_cost = 35000
} | ConvertTo-Json

$resp = Invoke-RestMethod -Uri http://localhost:8000/api/v1/preauth -Method Post -ContentType "application/json" -Body $body
$taskId = $resp.task_id; $runId = $resp.run_id
```

### Poll for result
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/preauth/$taskId"
```

### Submit feedback
```powershell
$fb = @{run_id = $runId; satisfactory = $true; reason = "Correct rejection"} | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8000/api/v1/feedback -Method Post -ContentType "application/json" -Body $fb
```

### Rebuild index
```powershell
python -m src.ingestion.ingest_pipeline --force
```

### Run tests
```powershell
python -m pytest -q
```

### Run evaluation
```powershell
python -m eval.evaluate_rag --report results/evaluation.json --prompt-version v1
```

### Worker scaling
```powershell
docker compose up --scale worker=3
```

---

## 5. Recovery Procedures

### API not responding
1. `docker compose ps` – check container state
2. `docker compose logs app` – check for startup errors
3. `docker compose restart app`
4. Verify Redis is healthy: `docker compose exec redis redis-cli ping`

### Worker not processing tasks
1. `docker compose logs worker`
2. Check Redis connection: `docker compose exec redis redis-cli keys "*"`
3. Restart worker: `docker compose restart worker`

### Circuit breaker OPEN
The circuit breaker opens after 3 consecutive LLM provider failures.
1. Wait 30 seconds for automatic HALF_OPEN transition
2. Submit one test request – success closes it, failure re-opens
3. Check provider connectivity manually

### Results file too large
```powershell
# Archive old results
Move-Item data/results.json data/results_archive_$(Get-Date -f yyyyMMdd).json
```

### Quarantine file inspection
```powershell
# View quarantined payloads
Get-Content data/quarantine_records.json | ConvertFrom-Json | ForEach-Object {
    Write-Host "ID: $($_.quarantine_id)  Time: $($_.quarantined_at)"
    Write-Host "Error: $($_.error)"
}
```

---

## 6. Load Testing

```powershell
# Beginner (declare SLO: p95 < 2s)
locust -f load_test/locustfile.py --host http://localhost:8000 --headless -u 5 -r 1 -t 1m

# Medium
locust -f load_test/locustfile.py --host http://localhost:8000 --headless -u 20 -r 2 -t 5m

# Stress
locust -f load_test/locustfile.py --host http://localhost:8000 --headless -u 50 -r 5 -t 5m

# Browser UI
locust -f load_test/locustfile.py --host http://localhost:8000
# Then open http://localhost:8089
```

---

## 7. Demonstration Checklist

1. `docker compose up --build` → verify `/health` returns healthy
2. Submit cataract 11-month → REJECT with Code-Excl02 citation
3. Submit cataract 24-month → APPROVE with sub-limit 40,000
4. Submit empty member_id → 422, check quarantine file
5. Submit cosmetic procedure → QUERY + MEDICAL_REVIEW escalation
6. Submit prompt injection → QUERY + guardrail reason
7. Open Grafana at http://localhost:3000
8. Run `python -m eval.evaluate_rag` → 25/25 pass

