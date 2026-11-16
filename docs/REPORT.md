# Final Report – Health Insurance Pre-Authorisation Desk

## 1. Problem and Scope

This project automates the first-level review of health-insurance pre-authorisation (preauth) requests. A hospital submits a patient's diagnosis, procedure, policy details, and estimated cost through a REST API. The system retrieves relevant clauses from policy documents, applies waiting-period and exclusion rules, verifies citation grounding, and returns a conservative, cited recommendation.

The system is an **academic prototype** demonstrating MLOps and LLMOps practices including agent orchestration, retrieval-augmented decision making, guardrails, observability, and reproducible evaluation. It does not replace a licensed insurance adjudicator.

**Scope covered:**
- REST API with async task queue
- Multi-node agent workflow with verification
- Policy corpus retrieval (token-overlap, deterministic)
- Waiting period and exclusion rules for 10+ clinical categories
- Prompt injection and output filtering guardrails
- Prometheus metrics, Grafana dashboard
- Docker Compose deployment with health checks
- 25-case evaluation suite with LLMOps metrics
- Locust load testing with SLO declaration

---

## 2. Architecture and Topology

```
Client / Hospital System
        │
        ▼
FastAPI (src/services/api.py)
  ├── Rate Limiter (20 req/min per client)
  ├── Cache (5-min TTL, SHA-256 keyed)
  ├── Validation → Quarantine (data/quarantine_records.json)
  └── Task Queue
        │
        ├── Local (synchronous, development)
        └── Celery + Redis (production)
              │
              ▼
        Worker (src/services/worker.py)
              │
              ▼
        Workflow Graph (src/agents/graph.py)
         Node 1: Input Guardrails
         Node 2: Clinical/Intake Agent  ──→  classify category, flag PED/exclusion
         Node 3: Coverage/Decision Agent ──→ 5-pass retrieval + business rules
         Node 4: Verification Agent  ──→  grounding check + consistency check
         Node 5: Verification retry (if first pass found issues)
         Node 6: Final grounding check
              │
              ▼
        PreAuthResponse → results.json
              │
              ▼
Prometheus /metrics → Grafana Dashboard
```

---

## 3. Agent Roles and Tools

### Node 2: Clinical/Intake Agent (`clinical_agent.py`)
- Classifies diagnosis+procedure text into 10 clinical categories
- Flags: daycare procedure, pre-existing conditions, permanent exclusions
- Sets `is_unsupported` for unrecognised or excluded categories

### Node 3: Coverage/Decision Agent (`coverage_agent.py`)
**5 retrieval passes using 3 tools:**

| Tool | Query | Purpose |
|---|---|---|
| `corpus_search` | base coverage query | Coverage eligibility |
| `corpus_search` | waiting period / Code-Excl02 | Exclusion check |
| `corpus_search` | sub-limit query | Sub-limit determination |
| `corpus_search` | daycare list query | Daycare eligibility |
| `clause_lookup` | "Code-Excl02" | Specific clause lookup |

**Decision rules applied:**
- Excluded category → QUERY + MEDICAL_REVIEW
- Pre-existing + < 48 months → QUERY + MEDICAL_REVIEW (Code-Excl01)
- Cataract + < 24 months → REJECT (Code-Excl02)
- Hernia/piles/fistula + < 24 months → REJECT (Code-Excl02)
- ENT (tonsil/sinus) + < 24 months → REJECT (Code-Excl02)
- Kidney stone/lithotripsy + < 24 months → REJECT (Code-Excl02)
- Joint replacement + < 24 months → REJECT (Code-Excl02)
- Initial 30-day waiting period for planned non-emergency
- Default eligible cases → APPROVE with sub-limit applied

### Node 4: Verification Agent (`verification.py`)
- Checks every citation is grounded in retrieved text (substring match)
- Checks APPROVE is not issued for unsupported categories or early PED
- Checks APPROVE is not issued without citations
- If issues found on first attempt: triggers a second search with alternate query
- If still unresolved: downgrades to QUERY + MEDICAL_REVIEW

**Execution bounds enforced:**
- Max steps: 10
- Max tool calls: 20
- Wall-clock deadline: 30 seconds

---

## 4. Verification and Loop Limits

The verification node runs twice if the first pass detects grounding issues. It performs a second corpus search with an alternate query to look for supporting evidence. If evidence is still missing, it escalates rather than approving.

Loop limits prevent runaway execution:
- `MAX_STEPS = 10` stops the graph if steps exceed threshold
- `MAX_TOOL_CALLS = 20` caps retrieval calls
- `DEADLINE_SECONDS = 30` enforces a wall-clock timeout

All limit violations result in QUERY escalation, never approval.

---

## 5. Deployment Boundaries

| Service | Image | Port | Persistence |
|---|---|---|---|
| `app` | custom Python 3.12 | 8000 | `preauth_data` volume |
| `worker` | custom Python 3.12 | — | `preauth_data` volume |
| `redis` | redis:7-alpine | 6379 | — |
| `prometheus` | prom/prometheus:v2.47.0 | 9090 | — |
| `grafana` | grafana/grafana:10.1.0 | 3000 | `grafana_data` volume |

Health checks:
- `app`: HTTP GET `/health` every 15s, 20s start period
- `redis`: `redis-cli ping` every 10s
- Worker and observability services: depends on healthy redis

---

## 6. Rejected Design Alternatives

| Alternative | Reason Rejected |
|---|---|
| LangGraph/CrewAI framework | Adds substantial dependency weight; a hand-rolled state machine achieves the same graph semantics for this scope without package conflicts on Python 3.13 |
| FAISS/Chroma vector store | Requires embedding model (sentencetransformers, ~500MB). Token-overlap retrieval is deterministic, dependency-free, and sufficient for the demonstrable corpus size; documented as a known limitation |
| OpenAI/Gemini API for decisions | Deterministic rule-based decisions are reproducible, auditable, and cost-free; LLM API calls add non-determinism and cost without improving the academic demonstration |
| Separate ingestion service | Ingestion runs at build time; a separate service adds orchestration complexity without benefit for a single-corpus demo |
| JWT authentication | Out of scope for academic prototype; documented as a production requirement |

---

## 7. Evaluation Results – Before/After Comparison

**Before change:** corpus had only 2 large chunks (whole files), retrieval returned only 2 results per query.

**After change:** corpus split into 27 fine-grained chunks with section boundaries and clause_id metadata, plus a comprehensive daycare procedures list. Retrieval returns up to 5 targeted chunks per pass.

| Metric | Before (2 chunks) | After (27 chunks) |
|---|---|---|
| Accuracy | 100% (5 cases) | 100% (25 cases) |
| Avg Groundedness | 1.0 | 1.0 |
| Avg Context Relevance | 0.60 | 0.26 |
| Avg Faithfulness | 1.0 | 1.0 |
| Avg Hallucination Rate | 0.0 | 0.0 |
| Avg Latency | 0.002s | 0.004s |

> [!NOTE]
> Context relevance is lower after the change because more diverse chunks are retrieved (sub-limit, daycare, exclusion sections that don't mention the specific procedure keyword). This is expected and correct — the retrieval now surfaces all relevant policy sections, not just those containing the exact procedure name.

---

## 8. p95 Target and Measured Results

**Declared SLO (before measurement):** p95 end-to-end latency < 2 seconds for the full submit-to-poll lifecycle.

**Measured Docker results (16 November 2026, 5 users, approximately 1-minute runs):**

| Deployment | Requests | Failures | Aggregate RPS | Aggregate p50 | Aggregate p95 | Max |
|---|---:|---:|---:|---:|---:|---:|
| 1 worker | 245 | 0 | 4.18 | 31 ms | 54 ms | 200 ms |
| 3 workers | 295 | 0 | 5.04 | 33 ms | 55 ms | 71 ms |

The Locust scenario exercises the complete submit-and-poll lifecycle. Its CSV
statistics aggregate the individual HTTP requests in that lifecycle rather
than recording one combined transaction timer. Every submission, poll,
invalid-request check, health check, and metrics check completed without a
failure in both final runs. The measured request p95 values are well below the
2-second SLO.

The rate limiter remains enabled at 20 submissions per minute per client. The
initial Docker test treated all Locust users as one client because they shared
the container-facing IP, causing HTTP 429 responses. The API now accepts an
optional `X-Client-ID` and falls back to source IP; the Locust script assigns a
stable identity to each virtual user. This preserves rate limiting while
allowing the benchmark to model multiple clients correctly.

---

## 9. Bottleneck and Scaling Findings

**Bottleneck identified:** The token-overlap retrieval is O(n*q) where n is the
number of chunks and q is the number of query tokens. With 27 chunks it is
negligible compared with request and queue overhead. The final workload did
not saturate the worker pool.

**Worker scaling measurement:**

- 1 worker: 4.18 aggregate requests/second, p95 54 ms, 0 failures.
- 3 workers: 5.04 aggregate requests/second, p95 55 ms, 0 failures.
- The three-worker run increased observed throughput by approximately 20.5%.
- The small five-user workload and very low workflow latency limit the visible
  scaling benefit; a larger workload would be needed to saturate the workers.
- `docker compose up --scale worker=3` successfully started and served three
  worker containers.

---

## 10. Cost per 100 Runs

Since the system uses deterministic token-overlap retrieval (no LLM API), cost is compute-only:

| Component | Cost/100 runs |
|---|---|
| LLM API calls | \$0 (not used in deterministic mode) |
| Compute (local) | ~\$0 (< 1 CPU-second total) |
| Compute (cloud estimate at 0.01 vCPU·s each) | ~\$0.001 |
| Redis (managed) | ~\$0.001 |
| **Total** | **~\$0.002 / 100 runs** |

Largest cost driver if LLM added: prompt tokens at ~200 tokens/request × \$0.002/1K tokens = \$0.04/100 runs.

---

## 11. Limitations and What Did Not Work

| Limitation | Impact | Workaround |
|---|---|---|
| Token-overlap retrieval (not semantic) | May miss semantically equivalent clauses | Demonstrated sufficient for structured policy text; production would use FAISS + embeddings |
| No LLM for free-text reasoning | Cannot handle ambiguous phrasing or novel conditions | Deterministic rules are auditable and reproducible; documented explicitly |
| In-memory result store | Results lost on API restart without file persistence | Mitigated by JSON file persistence; production would use PostgreSQL |
| No authentication/authorisation | Any client can submit requests | Documented production requirement; rate limiting is in place |
| Single corpus (2 simplified policies) | Coverage rules are illustrative, not complete | Demonstrable for all required test cases; documented in limitations |
| No OpenTelemetry tracing | Distributed traces not available | Structured JSON logs with run_id/correlation_id provide reconstruction capability |

---

## 12. Requirement-to-Evidence Matrix

| Req | Implementation | Test/Demo Evidence | Status |
|---|---|---|---|
| F1 REST contract | `src/services/api.py` routes + schemas | `test_api.py` → 202, 422 | ✅ |
| F2 validation/quarantine | Pydantic validators + `quarantine.py` | `test_api.py::test_invalid_payload_returns_422` | ✅ |
| F3 classification/entities | `clinical_agent.py` 10 categories | `test_workflow.py` cataract, hernia, cosmetic | ✅ |
| F4 binding retrieval | `coverage_agent.py` 5-pass retrieval | `test_ingestion.py::test_search_returns_relevant_results` | ✅ |
| F5 cited recommendation | `citation` list in PreAuthResponse | eval 25-case groundedness=1.0 | ✅ |
| F6 three routing outcomes | `Route` enum in PreAuthResponse | `test_contracts.py::TestRouteMapping` | ✅ |
| F7 safe escalation | Verification node + unsupported/PED paths | `test_workflow.py` cosmetic, PED, injection | ✅ |
| F8 health/metrics/logs | `/health`, `/metrics`, Prometheus | Live dashboard demo | ✅ |
| A1 agent framework/tools | Explicit 3-agent graph + 3 tools (`corpus_search`, `clause_lookup`, `request_field_lookup`) | `test_agent_architecture.py`, `test_workflow.py` | ✅ |
| A2 distinct agents | ClinicalAgent + CoverageAgent + VerificationAgent with explicit hand-off protocols | `test_agent_architecture.py`, `trace_formatter.py` | ✅ |
| A3 verification | `verification.py` with alternate search retry + safe escalation | `test_guardrails.py`, `test_agent_architecture.py` | ✅ |
| A4 async queue | FastAPI + Celery + local fallback | `test_api.py` submit/poll | ✅ |
| A5 reliability | Circuit breaker + rate limiter + idempotency | `services/circuit_breaker.py`, `rate_limiter.py` | ✅ |
| A6 agent metrics | Prometheus step_latency, escalation, tool_calls | Grafana dashboard | ✅ |
| A7 scaling | `docker compose up --scale worker=3` | RUNBOOK §6 | ✅ |
| A8 web client | Streamlit `src/client/app.py` | UI demo | ✅ |
| L1 retrieval/index | Token-overlap VectorStore + manifest | `test_ingestion.py` | ✅ |
| L2 prompt versions | `prompts/v1_conservative.txt`, `v2_detailed.txt` | eval v1 vs v2 comparison | ✅ |
| L3 evaluation | 25 cases, groundedness/faithfulness/hallucination | `results/evaluation_v1.json` | ✅ |
| L4 injection/output safety | `prompt_guard.py` + `filter_output` | `test_guardrails.py`, injection test | ✅ |
| L5 token/cost tracking | `token_usage`, `cost_usd` in PreAuthResponse | Metadata in result JSON | ✅ |
| L6 feedback/quality | `/api/v1/feedback` + `/api/v1/feedback/summary` | `test_api.py::TestFeedbackEndpoint` | ✅ |
| D1 contracts | Pydantic schemas with cross-field validation | `test_contracts.py` | ✅ |
| D2 ingestion metadata | `data/index_manifest.json` with hashes | `test_ingestion.py::test_ingest_creates_store` | ✅ |
| D3 Compose | 5 services, health checks, volumes | `docker compose config` | ✅ |
| D4 configuration hygiene | `.env.example`, `.gitignore`, no committed secrets | Repo scan | ✅ |
| D5 tracing/reconstruction | `run_id` in every result + step_timings | `test_workflow.py::test_response_has_run_id` | ✅ |
| D6 SLO/load test | SLO p95<2s declared; Locust profiles | RUNBOOK load testing commands | ✅ |
| D7 cache/rate limit | `cache.py` (5-min TTL) + `rate_limiter.py` (20/min) | `circuit_breaker.py`, cache_hits counter | ✅ |
| D8 runbook/incident log | `RUNBOOK.md`, `INCIDENT_LOG.md` | Reviewer inspection | ✅ |

