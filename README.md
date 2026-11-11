
# Health Insurance Pre-Authorisation Desk

## Overview

Automated first-level review of health-insurance pre-authorisation requests.
Accepts patient and treatment information, retrieves relevant policy clauses,
applies waiting-period and exclusion rules, verifies citation grounding, and
returns a conservative, cited recommendation.

**Three routing outcomes:**
- `approve-recommended`: request meets all coverage requirements
- `query-to-hospital`: evidence is insufficient; hospital should provide more information
- `medical-review`: escalated for human review (exclusion, pre-existing condition, injection attempt, etc.)

---

## Quick Start (Docker)

```powershell
# 1. Copy env file
copy .env.example .env

# 2. Start all services
docker compose up --build

# 3. Verify health
Invoke-RestMethod http://localhost:8000/health

# 4. Submit a request (11-month cataract → REJECT)
$body = @{
    member_id = "M-1001"; policy_number = "P-2001"
    policy_name = "Care Supreme"; diagnosis_name = "Cataract"
    procedure_name = "Phacoemulsification"; admission_type = "PLANNED"
    policy_tenure_months = 11; estimated_cost = 35000
} | ConvertTo-Json
$resp = Invoke-RestMethod -Uri http://localhost:8000/api/v1/preauth -Method Post -ContentType "application/json" -Body $body
$taskId = $resp.task_id

# 5. Poll for result
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/preauth/$taskId"
```

**Services:**

| Service | URL |
|---|---|
| API + Swagger | http://localhost:8000/docs |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (admin/admin) |

---

## Local Development

```powershell
pip install -r requirements.txt
python -m src.ingestion.ingest_pipeline --force
uvicorn src.services.api:app --reload
# In another terminal:
streamlit run src/client/app.py
```

---

## Architecture

```
Client (Hospital System / Streamlit)
        │
        ▼
FastAPI REST API (src/services/api.py)
  ├── Rate Limiter (20 req/min)
  ├── Result Cache (5-min TTL)
  ├── Pydantic Validation → Quarantine (data/quarantine_records.json)
  └── Celery/Redis Queue ─────────────────────┐
                                              ▼
                                    Worker (src/services/worker.py)
                                              │
                                              ▼
                                    Agent Graph (src/agents/graph.py)
                                     ┌── Node 1: Input Guardrails
                                     ├── Node 2: Clinical Agent
                                     ├── Node 3: Coverage Agent (5-pass retrieval)
                                     ├── Node 4: Verification Agent
                                     └── Node 5: Verification Retry
                                              │
                                              ▼
                                    PreAuthResponse → results.json
                                              │
                                    Prometheus /metrics → Grafana
```

---

## API Reference

### POST /api/v1/preauth → 202 Accepted

```json
{
  "member_id": "M-1001",
  "policy_number": "P-2001",
  "policy_name": "Care Supreme",
  "diagnosis_name": "Cataract",
  "procedure_name": "Phacoemulsification",
  "admission_type": "PLANNED",
  "policy_tenure_months": 11,
  "estimated_cost": 35000
}
```

Response:
```json
{"task_id": "...", "run_id": "...", "correlation_id": "...", "status": "PENDING"}
```

### GET /api/v1/preauth/{task_id}

```json
{
  "task_id": "...",
  "status": "SUCCESS",
  "result": {
    "recommendation": "REJECT",
    "route": "medical-review",
    "reason": "Cataract surgery is subject to a 24-month Code-Excl02 waiting period.",
    "indicative_limit": 0,
    "citations": [{"source": "care_supreme_policy.txt", "clause": "..."}],
    "escalation_required": false,
    "verification_passed": true,
    "run_id": "...",
    "step_timings": {"clinical_classification": 0.0012, "coverage_verification": 0.003}
  }
}
```

### GET /health | GET /metrics

### POST /api/v1/feedback
```json
{"run_id": "...", "satisfactory": true, "reason": "Correct rejection"}
```

### GET /api/v1/feedback/summary

---

## Testing and Evaluation

```powershell
# Unit and API tests (56 tests)
python -m pytest -q

# Evaluation suite (25 cases, 4 metrics)
python -m eval.evaluate_rag --report results/evaluation.json

# Load test
locust -f load_test/locustfile.py --host http://localhost:8000 --headless -u 5 -r 1 -t 1m

# Worker scaling test
docker compose up --scale worker=3
```

---

## Repository Structure

```
.
├── data/
│   ├── corpus/                    # Policy documents (txt)
│   ├── vector_store.json          # Ingested searchable chunks
│   ├── index_manifest.json        # Build metadata
│   └── quarantine_records.json    # Invalid payloads (runtime)
├── data_contracts/
│   └── preauth_schema.py          # Pydantic schemas + enums
├── eval/
│   ├── eval_dataset.json          # 25 evaluation cases
│   └── evaluate_rag.py            # Batch evaluator + LLMOps metrics
├── load_test/
│   └── locustfile.py              # Locust load test
├── observability/
│   ├── prometheus.yml
│   ├── grafana_dashboard.json
│   ├── grafana_datasources.yml
│   └── grafana_dashboards.yml
├── prompts/
│   ├── v1_conservative.txt        # Prompt variant 1
│   └── v2_detailed.txt            # Prompt variant 2
├── src/
│   ├── agents/
│   │   ├── clinical_agent.py      # Classification node
│   │   ├── coverage_agent.py      # Retrieval + decision node
│   │   ├── verification.py        # Citation grounding node
│   │   ├── graph.py               # Workflow orchestration
│   │   ├── state.py               # AgentState TypedDict
│   │   └── tools.py               # corpus_search, clause_lookup, field_lookup
│   ├── client/
│   │   └── app.py                 # Streamlit UI
│   ├── guardrails/
│   │   └── prompt_guard.py        # Injection detection, output filter, grounding
│   ├── ingestion/
│   │   ├── chunker.py             # Text splitting + clause_id extraction
│   │   ├── vector_store.py        # Token-overlap search + clause lookup
│   │   └── ingest_pipeline.py     # CLI ingestor with manifest + idempotency
│   └── services/
│       ├── api.py                 # FastAPI endpoints + Prometheus
│       ├── cache.py               # In-memory result cache
│       ├── circuit_breaker.py     # Provider circuit breaker
│       ├── rate_limiter.py        # Per-client rate limiting
│       ├── quarantine.py          # Invalid payload persistence
│       └── worker.py              # Celery task + local fallback
├── tests/
│   ├── conftest.py                # Temp-dir isolation fixture
│   ├── test_api.py                # API endpoint tests
│   ├── test_contracts.py          # Schema validation tests
│   ├── test_guardrails.py         # Guardrail tests
│   ├── test_ingestion.py          # Ingestion + retrieval tests
│   └── test_workflow.py           # End-to-end workflow tests
├── REPORT.md                      # Final report
├── RUNBOOK.md                     # Operations runbook
├── INCIDENT_LOG.md                # Development incident log
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Limitations

This is an academic prototype. Known limitations:

- **Token-overlap retrieval** (not semantic) – may miss paraphrased policy text
- **Deterministic rules only** – no LLM for free-text ambiguity
- **In-process result store** – not durable across restarts (mitigated by JSON file)
- **Simplified policy corpus** – 2 policy documents, illustrative clauses only
- **No authentication** – rate limiting only; no JWT/API keys
- **No OpenTelemetry tracing** – run_id-based log correlation instead

See `REPORT.md` §11 for the full limitations table.
