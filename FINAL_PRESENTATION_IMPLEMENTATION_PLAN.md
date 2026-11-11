# Final Presentation Implementation Plan

## 1. Objective

Bring the Health Insurance Pre-Authorisation Desk from its current working
prototype to a demonstrable final submission aligned with the requirements in
`MiniProject_03_Health_PreAuth_Desk (1).pdf`.

The final system must:

- accept and validate pre-authorisation requests through a documented REST API;
- make conservative, cited coverage recommendations;
- escalate uncertain, unsupported, conflicting, or unsafe cases;
- expose the complete run through metrics, logs, traces, and persisted evidence;
- run from a clean clone with Docker Compose;
- provide reproducible evaluation and load-test results;
- include the report, runbook, incident log, and presentation evidence.

The project is not expected to implement every production feature fully. Any
requirement that is deliberately simplified must be documented with the
reason, limitation, and demonstration evidence.

## 2. Current Baseline

Already present:

- FastAPI submission and polling endpoints.
- Pydantic request/response contracts.
- Quarantine handling for malformed payloads.
- Clinical classification and two-pass retrieval.
- Citation grounding guardrail.
- Celery/Redis integration with local fallback.
- Streamlit client.
- Prometheus endpoint and Docker Compose skeleton.
- Passing unit tests and a five-case evaluator.

The current retrieval implementation is deterministic and dependency-light.
The evaluation currently contains only five cases and does not yet produce the
required LLMOps metrics.

## 3. Delivery Strategy

Implement in the following order:

1. Stabilise contracts and workflow safety.
2. Introduce explicit agent orchestration and tool boundaries.
3. Add policy evidence, escalation, and guardrails.
4. Add reliability, observability, and reproducibility.
5. Add evaluation, cost tracking, and load testing.
6. Make Docker Compose reproducible.
7. Prepare the report and live demonstration.

After each phase, run the targeted tests and update the evidence checklist.
Do not claim a requirement is complete until there is either automated
evidence or a repeatable demonstration procedure.

## 4. Phase 0 - Protect the Baseline

### Tasks

- Add tests for the existing cataract rejection and approval paths.
- Add API tests for:
  - valid submission returning HTTP `202`;
  - polling a completed task;
  - invalid payload returning HTTP `422`;
  - invalid payload being quarantined;
  - malformed input not starting a workflow.
- Add a test fixture that isolates result and quarantine files in a temporary
  directory.
- Ensure `.env`, generated result files, vector-store output, caches, and
  Python bytecode are excluded from the final repository where appropriate.
- Keep `.env.example` complete and ensure no secret values are committed.

### Exit criteria

- Existing tests and new API tests pass.
- A clean test run does not modify tracked source files.
- The baseline workflow remains deterministic.

## 5. Phase 1 - Complete Data Contracts and Safe Routing

### Tasks

- Extend `PreAuthRequest` with explicit cross-field validation:
  - planned admissions require the relevant planned-admission fields;
  - emergency admissions follow the emergency path;
  - estimated cost and tenure remain within documented limits;
  - reject contradictory admission/procedure combinations where applicable.
- Define stable public response schemas for:
  - submission;
  - pending status;
  - successful result;
  - query/escalation result;
  - failed run.
- Add field-level error codes to quarantine records.
- Add a request/run correlation ID to every accepted request.
- Define the three routing outcomes required by the PDF:
  - `approve-recommended`;
  - `query-to-hospital`;
  - `medical-review`.
- Preserve backward compatibility with the current `APPROVE`, `REJECT`, and
  `QUERY` values through an explicit mapping if necessary.
- Add an unsupported-corpus path that always escalates instead of approving.
- Add a pre-existing-condition indicator/path that escalates to medical review.
- Add a conflicting-clause path that escalates.

### Exit criteria

- No malformed request starts an agent run.
- Every terminal response has a reason, route, evidence status, and run ID.
- Unknown clinical categories do not receive a confident approval.

## 6. Phase 2 - Implement the Required Agent Architecture

### Tasks

- Use LangGraph or CrewAI for the reasoning layer.
- Define an explicit graph state containing:
  - request entities;
  - classification;
  - retrieved passages;
  - tool calls;
  - route;
  - verification status;
  - retries;
  - step timings;
  - prompt version;
  - token/cost data;
  - correlation and run IDs.
- Create at least two genuinely distinct agents:
  1. **Clinical/Intake Agent**
     - classify admission and clinical category;
     - extract policy and clinical entities;
     - flag possible pre-existing conditions or unsupported terminology.
  2. **Coverage/Decision Agent**
     - retrieve coverage, waiting-period, exclusion, sub-limit, and
       day-care provisions;
     - derive a conservative recommendation;
     - hand off to verification.
- Add a dedicated verification node/agent that:
  - checks every citation against retrieved text;
  - checks that the recommendation is supported by all binding provisions;
  - requests a second search with a different query if evidence is incomplete;
  - escalates if verification still fails.
- Define at least three callable tools:
  - corpus search;
  - clause-identifier lookup;
  - request-field lookup.
- Make retrieval a tool available to the agent rather than an unconditional
  fixed pipeline stage.
- Bound the graph by:
  - maximum steps;
  - maximum tool calls;
  - per-tool timeout;
  - total wall-clock deadline.
- Document agent hand-offs and mid-run failure behavior.

### Exit criteria

- A trace demonstrates the tool calls and hand-offs for the cataract case.
- An unsupported answer cannot pass verification.
- Tool-call and step limits stop runaway execution.

## 7. Phase 3 - Retrieval and Corpus Completion

### Tasks

- Confirm that the corpus contains:
  - one complete retail health-insurance policy wording;
  - the same insurer's day-care procedure list.
- Record source name, version, effective date, and retrieval date for each
  document.
- Document chunking, clause preservation, page/source metadata, and the
  embedding/retrieval strategy.
- Replace or extend the custom token-overlap store with LangChain or
  LlamaIndex orchestration and FAISS or Chroma indexing, as required by the
  rubric.
- Keep indexing deterministic and make re-embedding possible without
  rebuilding unrelated metadata.
- Make ingestion idempotent.
- Persist an index manifest containing:
  - build timestamp;
  - corpus versions;
  - embedding/index version;
  - chunk count;
  - processing duration;
  - throughput.
- Add retrieval tests for:
  - coverage clause;
  - cataract waiting-period clause;
  - exclusion clause;
  - day-care clause;
  - no-support case.

### Exit criteria

- A clean-clone command rebuilds the index.
- The cataract query returns both the coverage and waiting-period evidence.
- Every returned citation has source and clause/page metadata.

## 8. Phase 4 - Guardrails, Reliability, and Failure Handling

### Tasks

- Add prompt-injection detection to every free-text field that reaches a
  model or agent.
- Add output filtering so the system never claims to authorise an admission.
- Add toxicity/safety checks for model-facing input and output.
- Implement timeouts for every model and tool call.
- Implement bounded retries with exponential backoff.
- Implement a provider circuit breaker.
- Define and implement graceful degradation:
  - local deterministic fallback where safe;
  - otherwise `QUERY` or `MEDICAL_REVIEW`;
  - never return a confident answer for an incomplete run.
- Add explicit `FAILED`, `ESCALATED`, and `TIMEOUT` persistence states.
- Ensure Celery task failures are visible and do not appear as successful
  recommendations.
- Add idempotency handling for repeated submission keys.
- Add per-client rate limiting.
- Add justified caching for retrievals or completed runs and measure its
  effect.

### Exit criteria

- Demonstration covers:
  - prompt injection blocked;
  - unsupported case escalated;
  - provider failure opens the circuit breaker;
  - timeout/retry behavior;
  - incomplete run never becomes an approval.

## 9. Phase 5 - Prompt and LLMOps Management

### Tasks

- Store prompts as versioned artifacts under a dedicated prompts directory.
- Record prompt version in every result and trace.
- Define at least two prompt variants.
- Run both variants on the same evaluation set.
- Record:
  - groundedness;
  - context relevance;
  - faithfulness;
  - hallucination rate;
  - pass/fail accuracy;
  - latency;
  - token usage;
  - cost.
- Add per-step and per-run token/cost accounting.
- Calculate cost per 100 runs and identify the largest cost driver.
- Add a feedback endpoint allowing a caller to mark a result satisfactory or
  unsatisfactory with a reason.
- Persist feedback and produce an aggregate quality summary.

### Exit criteria

- Prompt versions are visible in stored run evidence.
- Variant comparison is reproducible from the command line.
- Cost and feedback summaries can be generated without manual editing.

## 10. Phase 6 - Evaluation Suite

### Tasks

- Expand `eval/eval_dataset.json` to at least 20 fixed scenarios.
- Include expected route/recommendation and supporting passage identifiers for
  every scenario.
- Cover:
  - cataract before and after waiting period;
  - emergency admission;
  - day-care procedure;
  - permanent exclusion;
  - sub-limit;
  - room-category mismatch;
  - pre-existing condition;
  - unsupported procedure;
  - conflicting clauses;
  - missing policy evidence;
  - malformed/edge requests;
  - prompt injection;
  - citation failure;
  - timeout/fallback.
- Implement a batch evaluator runnable from the command line.
- Define and document metric computation:
  - **Groundedness:** claims supported by retrieved passages;
  - **Context relevance:** retrieved passages relevant to the request;
  - **Faithfulness:** answer consistent with the retrieved context;
  - **Hallucination rate:** unsupported claims divided by total claims.
- Generate machine-readable JSON and a human-readable report.
- Run the evaluation before and after one deliberate change, such as a
  prompt, chunking, or verification change.
- Include the before/after results in the final report.

### Exit criteria

- At least 20 cases run successfully from a clean command.
- The required metrics are reported before and after the chosen change.
- The 11-month cataract scenario passes with both required passages shown.

## 11. Phase 7 - Observability and Reconstruction

### Tasks

- Add structured JSON logging throughout API, workers, agents, tools, and
  ingestion.
- Propagate correlation ID and run ID across every service and agent step.
- Add OpenTelemetry tracing exported to Jaeger or Grafana Tempo.
- Persist reconstructable run evidence:
  - request;
  - validation result;
  - every tool call;
  - search query;
  - retrieved passage;
  - prompt version;
  - model/provider response metadata;
  - retries;
  - per-step latency;
  - cost;
  - verification outcome;
  - final route.
- Add Prometheus metrics for:
  - request count;
  - success/error/escalation count;
  - end-to-end latency;
  - per-step latency;
  - p50/p95 latency;
  - tool calls;
  - retry rate;
  - circuit state;
  - queue depth;
  - worker uptime;
  - ingestion freshness and throughput.
- Configure Prometheus to scrape every relevant service.
- Create a Grafana dashboard showing:
  - throughput;
  - availability;
  - error rate;
  - p50/p95 latency;
  - resource utilisation;
  - agent success rate;
  - escalation rate.

### Exit criteria

- Given a run ID, the entire run can be reconstructed.
- The dashboard displays live or recorded evidence for the required metrics.
- Logs from API and worker share the same correlation/run ID.

## 12. Phase 8 - Docker Compose and Deployment

### Tasks

- Define at least four meaningful services with explicit boundaries:
  - API;
  - agent worker;
  - Redis/queue;
  - observability service(s).
- Add health checks and dependency readiness conditions.
- Ensure `docker compose up --build` works from a clean clone.
- Ensure the API waits for required dependencies before accepting work.
- Ensure generated data uses mounted volumes where persistence is required.
- Verify:
  - `docker compose up`;
  - valid request;
  - invalid request;
  - worker processing;
  - metrics;
  - dashboard;
  - graceful service restart.
- Verify worker scaling:
  - `docker compose up --scale worker=3`;
  - compare throughput and p95 latency against one worker;
  - document the actual bottleneck if scaling does not improve results.
- Remove obsolete or misleading README claims.

### Exit criteria

- No required component runs outside containers during the demonstration.
- Compose health checks become healthy.
- Scaling results are recorded and reproducible.

## 13. Phase 9 - Load and Performance Validation

### Tasks

- Declare a p95 end-to-end SLO before collecting results.
- Add a stub model/provider service with fixed responses and realistic delay.
- Configure Locust to measure the full lifecycle:
  - submit;
  - poll;
  - final result.
- Run and record:
  - RPS;
  - p50;
  - p95;
  - failure count;
  - queue latency;
  - worker utilisation.
- Run beginner, medium, and stress profiles.
- Identify the concurrency at which the SLO fails.
- Compare one worker and three workers.
- Measure caching enabled versus disabled.
- Include the exact command, environment, date, and result files in the
  report.

### Exit criteria

- SLO was declared before measurement.
- Results cover the complete run, not only the submission endpoint.
- Bottleneck and scaling conclusion are evidence-based.

## 14. Phase 10 - Documentation and Presentation Package

### Required files

- `README.md` - clean-clone setup and complete runbook.
- `REPORT.md` or equivalent final report containing:
  - problem and scope;
  - architecture/topology;
  - agent roles and tools;
  - verification and loop limits;
  - deployment boundaries;
  - rejected design alternatives;
  - evaluation before/after results;
  - p95 target and measured results;
  - bottleneck and scaling findings;
  - cost per 100 runs;
  - limitations and what did not work.
- `RUNBOOK.md` - startup, health checks, common commands, recovery steps.
- `INCIDENT_LOG.md` - at least one genuine development failure with date,
  symptom, diagnosis, impact, fix, and prevention.
- `.env.example` - all runtime configuration keys without secrets.
- Evaluation dataset and scripts.
- Architecture diagram showing service and agent boundaries.
- Optional `presentation/` directory containing screenshots, commands, and
  recorded result JSON.

### Live demonstration checklist

1. Start the system from a clean clone with Docker Compose.
2. Submit a valid request and show a cited recommendation.
3. Reconstruct one run end to end using its run ID.
4. Submit malformed input and show quarantine plus no agent run.
5. Submit an unsupported case and show escalation.
6. Trigger citation verification failure and show retry/escalation.
7. Submit a prompt-injection attempt and show guardrail behavior.
8. Demonstrate provider failure, circuit breaker, and fallback.
9. Show Locust results, SLO, p95, and worker-scaling evidence.
10. Demonstrate planned cataract surgery at 11 months and show both
    coverage and waiting-period passages.

## 15. Requirement-to-Evidence Matrix

Maintain this matrix in the final report and update it as work is completed.

| PDF requirement | Implementation evidence | Test/demo evidence | Status |
|---|---|---|---|
| F1 REST contract | API route and schema | API contract test | Pending |
| F2 validation/quarantine | Pydantic and quarantine service | malformed request demo | Partial |
| F3 classification/entities | clinical agent | classification tests | Partial |
| F4 binding retrieval | coverage agent/index | cataract retrieval test | Partial |
| F5 cited recommendation | response and grounding guard | citation demo | Partial |
| F6 three routing outcomes | routing model | route tests | Pending |
| F7 safe escalation | verification/fallback | unsupported/conflict demo | Pending |
| F8 health/metrics/logs | observability stack | dashboard demo | Partial |
| A1 agent framework/tools | LangGraph/CrewAI and tools | trace | Pending |
| A2 distinct agents | topology and hand-off | run trace | Partial |
| A3 verification | verifier and retry/escalation | unsupported citation demo | Partial |
| A4 async queue | FastAPI/Celery | submit/poll test | Partial |
| A5 reliability | timeout/retry/circuit breaker | failure demo | Pending |
| A6 agent metrics | Prometheus/Grafana | dashboard | Pending |
| A7 scaling | Compose worker scaling | load report | Pending |
| A8 web client | Streamlit UI | UI demo | Partial |
| L1 retrieval/index | LangChain/LlamaIndex + FAISS/Chroma | ingestion test | Pending |
| L2 prompt versions | prompt artifacts/comparison | variant report | Pending |
| L3 evaluation | 20+ cases and four metrics | batch report | Pending |
| L4 injection/output safety | input/output guardrails | injection demo | Partial |
| L5 token/cost tracking | usage records | cost report | Pending |
| L6 feedback/quality | feedback endpoint | feedback report | Pending |
| D1 contracts | schemas and quarantine | API tests | Partial |
| D2 ingestion metadata | manifest and metrics | rebuild test | Pending |
| D3 Compose | services/health checks | clean-clone startup | Partial |
| D4 configuration hygiene | `.env.example` | repository scan | Partial |
| D5 tracing/reconstruction | OTel/logs/evidence store | run reconstruction | Pending |
| D6 SLO/load test | stub and Locust | performance report | Pending |
| D7 cache/rate limit | middleware/cache | comparison report | Pending |
| D8 runbook/incident log | documentation files | reviewer inspection | Pending |

## 16. Final Validation Commands

Run these from the repository root before submission. Adjust commands only if
the final implementation changes the service names.

```powershell
python -m compileall -q src data_contracts eval load_test tests
python -m pytest -q
python -m eval.evaluate_rag --report results\evaluation.json
python -m src.ingestion.ingest_pipeline --corpus data\corpus --store data\vector_store.json
docker compose config
docker compose up --build
docker compose ps
locust -f load_test\locustfile.py --host http://localhost:8000 --headless -u 5 -r 1 -t 1m
```

Also manually verify:

- `/health` is healthy;
- `/metrics` exposes the expected counters and histograms;
- the dashboard loads;
- every demonstration case has a saved run ID and evidence file;
- no secrets are present in tracked files;
- the README works for a person unfamiliar with the project.

## 17. Definition of Done

The project is ready for final presentation only when:

- all critical F, A, and D requirements have an implementation and evidence;
- the 11-month cataract case is correctly handled with both citations;
- unsupported and unsafe cases escalate;
- the clean-clone Docker demonstration succeeds;
- tests, evaluation, and load tests have reproducible outputs;
- the final report, runbook, incident log, `.env.example`, and evaluation set
  are committed;
- the requirement-to-evidence matrix contains no unexplained `Pending` items;
- known limitations are presented honestly.
