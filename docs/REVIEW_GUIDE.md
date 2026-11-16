# Health Insurance Pre-Authorisation Desk

## Review Guide

This guide explains the current implementation in both simple and technical
terms. It is intended for project review, presentation, and viva discussion.

---

## 1. The Problem

### In layman terms

Before a patient is admitted to a hospital, the hospital sends an insurance
pre-authorisation request. The insurer must quickly decide:

- Is the treatment covered?
- Has the policy waiting period been completed?
- Is the treatment excluded?
- Is there a limit on the amount payable?
- Should the request be approved, sent back for more information, or reviewed
  by a medical officer?

This is difficult because the relevant information is usually spread across
different parts of a long policy document. For example, the policy may say
that cataract surgery is covered in one section, while a different section
states that cataract treatment has a 24-month waiting period.

A system that only finds the coverage paragraph may incorrectly approve a
patient whose policy is only 11 months old.

### In technical terms

The problem is a policy-grounded decision-support workflow. It must combine:

1. Structured request validation.
2. Clinical and admission classification.
3. Retrieval of all policy provisions that can affect the decision.
4. Deterministic coverage and waiting-period rules.
5. Evidence verification and citation grounding.
6. Conservative routing when the available evidence is incomplete or
   contradictory.
7. Asynchronous execution, persistence, observability, and evaluation.

The system provides a recommendation only. It does not authorise an admission
and does not replace a medical officer or insurance adjudicator.

---

## 2. Our Solution

### In layman terms

The application works like a careful first-level insurance desk assistant:

1. It checks whether the submitted request is valid.
2. It identifies what kind of treatment and admission are being requested.
3. It searches the policy documents for coverage information.
4. It searches again for exclusions, waiting periods, sub-limits, and
   day-care rules.
5. It applies the relevant policy rules.
6. It checks that the explanation is supported by the text it found.
7. It returns a recommendation with the supporting clauses.
8. If it cannot safely prove the answer, it escalates instead of guessing.

For the difficult demonstration case:

- cataract surgery;
- planned admission;
- policy tenure of 11 months;

the system finds both the coverage information and the 24-month waiting
period, and returns a rejection/escalation-oriented result rather than an
unsupported approval.

### In technical terms

The implementation is a FastAPI service backed by a Celery/Redis task queue.
The reasoning workflow is a bounded, hand-written state graph with separate
clinical, coverage, and verification responsibilities.

The major stages are:

```text
HTTP request
    ↓
Pydantic validation and cross-field checks
    ↓
Input guardrails
    ↓
Clinical/intake classification
    ↓
Coverage decision with multiple retrieval passes
    ↓
Citation and consistency verification
    ↓
Retry with an alternate search when verification fails
    ↓
Conservative final route
    ↓
Persisted result, metrics, and run metadata
```

The workflow exposes three callable retrieval-related tools:

- corpus search;
- clause lookup by identifier;
- request-field lookup.

The tools are executed through a centralized runner that records calls,
enforces limits, and exposes timeout/failure outcomes. The execution is
bounded by step, tool-call, and wall-clock limits. An unverified result is
downgraded to a query or medical-review route.

---

## 3. Main Components

| Component | Purpose |
|---|---|
| [data_contracts/preauth_schema.py](./data_contracts/preauth_schema.py) | Defines request, response, route, citation, and validation models |
| [src/services/api.py](./src/services/api.py) | FastAPI endpoints, validation handling, metrics, feedback, cache, and rate limiting |
| [src/services/worker.py](./src/services/worker.py) | Celery task execution and local development fallback |
| [src/agents/clinical_agent.py](./src/agents/clinical_agent.py) | Classifies the admission and clinical category |
| [src/agents/coverage_agent.py](./src/agents/coverage_agent.py) | Performs policy retrieval and applies coverage rules |
| [src/agents/verification.py](./src/agents/verification.py) | Checks grounding and decision consistency |
| [src/agents/graph.py](./src/agents/graph.py) | Orchestrates the bounded workflow |
| [src/agents/state.py](./src/agents/state.py) | Typed workflow state, tool-call records, hand-offs, and trace events |
| [src/agents/tools.py](./src/agents/tools.py) | Retrieval and request-field tools |
| [src/agents/trace_formatter.py](./src/agents/trace_formatter.py) | Generates presentation traces for canonical scenarios |
| [src/guardrails/prompt_guard.py](./src/guardrails/prompt_guard.py) | Detects injection attempts and filters unsafe output |
| [src/ingestion/ingest_pipeline.py](./src/ingestion/ingest_pipeline.py) | Builds the searchable policy store and index manifest |
| [src/ingestion/vector_store.py](./src/ingestion/vector_store.py) | Deterministic token-overlap retrieval and clause lookup |
| [src/client/app.py](./src/client/app.py) | Streamlit user interface |
| [eval/evaluate_rag.py](./eval/evaluate_rag.py) | Runs the fixed evaluation dataset and calculates metrics |
| [load_test/locustfile.py](./load_test/locustfile.py) | Exercises the complete API workflow under load |

---

## 4. Request Lifecycle

### Step 1: Validate the request

The API accepts a typed JSON request containing member, policy, diagnosis,
procedure, admission type, policy tenure, and estimated cost.

Validation includes:

- required fields;
- string length limits;
- valid admission categories;
- non-negative policy tenure;
- positive estimated cost;
- cross-field constraints such as estimated cost versus sum insured;
- day-care cost limits.

Invalid requests return HTTP `422` and are stored in the quarantine file with
field-level error information. They do not start a workflow.

### Step 2: Assign execution metadata

Accepted requests receive task, run, and correlation identifiers. These
identifiers connect the API response, worker result, metrics, and stored
workflow metadata.

The API also applies a five-minute result cache and a sliding-window limit of
20 submissions per minute per client. Clients may provide `X-Client-ID`;
otherwise the source IP is used.

### Step 3: Apply input guardrails

Free-text fields are checked for prompt-injection patterns and unsafe input.
An injection attempt is routed for review rather than being treated as an
ordinary policy request.

### Step 4: Classify the clinical request

The clinical agent normalizes the diagnosis and procedure and maps them to
known categories such as:

- cataract surgery;
- renal treatment;
- cardiac treatment;
- hernia or piles;
- ENT procedures;
- joint replacement;
- general hospitalisation;
- unsupported or excluded treatment.

It also detects relevant admission and risk flags, such as day-care handling,
possible pre-existing disease, and permanent exclusions.

### Step 5: Retrieve policy evidence

The coverage agent performs several searches instead of relying on one
coverage query. The searches cover:

- base coverage;
- waiting periods and exclusions;
- clause identifiers such as `Code-Excl02`;
- sub-limits;
- day-care procedure eligibility.

Retrieved clauses retain source and clause metadata so that the final answer
can be audited.

### Step 6: Apply deterministic rules

Examples of implemented rules include:

- cataract surgery before 24 months: reject or escalate according to the
  route mapping;
- certain listed procedures before their waiting period: reject;
- possible pre-existing condition before the required tenure: medical review;
- unsupported or excluded category: query or medical review;
- eligible treatment: approve recommendation with the applicable limit;
- no supporting clause: query rather than fabricate an answer.

### Step 7: Verify the answer

The verification stage checks that:

- every citation exists in the retrieved clauses;
- the recommendation is consistent with the retrieved policy evidence;
- approval is not issued for unsupported or unsafe cases;
- an approval has supporting citations;
- verification failures trigger an alternate search or escalation.

### Step 8: Return and persist the result

The API initially returns a task identifier. The caller polls the status
endpoint until the worker stores a completed result. The result includes:

- recommendation;
- route;
- reason;
- indicative limit;
- citations;
- retrieved clauses;
- escalation flag;
- verification status;
- run metadata;
- step timings;
- tool-call and token/cost metadata where applicable.

Worker result writes use an atomic temporary-file replacement. This prevents a
concurrent poll from reading a partially written JSON result.

---

## 5. Example Demonstration Cases

### Case A: Cataract at 11 months

**Input:** planned cataract surgery, policy tenure 11 months.

**Expected behavior:**

- retrieve coverage evidence;
- retrieve the 24-month waiting-period evidence;
- cite the relevant clause;
- do not approve the request;
- return `REJECT` with the documented conservative route and citation.

### Case B: Cataract at 24 months

**Input:** planned cataract surgery, policy tenure 24 months.

**Expected behavior:**

- waiting period is satisfied;
- return an approval recommendation if coverage evidence is present;
- apply the documented sub-limit or indicative limit;
- include citations.

### Case C: Unsupported procedure

**Input:** a procedure not covered by the indexed corpus.

**Expected behavior:**

- insufficient evidence is detected;
- the system escalates;
- it does not invent a policy clause or return a confident approval.

### Case D: Malformed request

**Input:** missing required field or invalid value.

**Expected behavior:**

- return HTTP `422`;
- store the raw request and field-level errors;
- do not enqueue or execute an agent workflow.

### Case E: Prompt injection attempt

**Input:** instructions embedded in a diagnosis or procedure field attempting
to override the policy rules.

**Expected behavior:**

- guardrail detects the attempt;
- the request is routed conservatively;
- the system does not follow the injected instruction.

### Case F: Verification failure and retry

The presentation trace generator includes a controlled ungrounded-citation
scenario. The verification agent detects the issue, performs an alternate
search, and escalates if the result cannot be grounded. This demonstrates
that verification is an active workflow transition rather than only a final
boolean check.

---

## 6. Results Obtained

### Automated tests

The repository currently reports:

```text
78 passed
```

The tests cover contracts, API behavior, quarantine, guardrails, ingestion,
retrieval, workflow decisions, feedback, escalation paths, agent boundaries,
tool limits, verification retry, trace reconstruction, and per-client rate
limiting.

### Evaluation suite

The fixed evaluation contains 25 cases:

| Metric | Current result |
|---|---:|
| Cases | 25 |
| Passed | 25 |
| Accuracy | 1.0 |
| Average groundedness | 1.0 |
| Average faithfulness | 1.0 |
| Average hallucination rate | 0.0 |
| Average context relevance | 0.262 |
| Average workflow latency | approximately 0.004 seconds |

The generated result is stored in
[results/evaluation.json](./results/evaluation.json).

### Before-and-after retrieval comparison

The documented retrieval change split the original two large chunks into 27
more targeted chunks with section and clause metadata.

| Metric | Before | After |
|---|---:|---:|
| Evaluation cases | 5 | 25 |
| Accuracy | 100% | 100% |
| Groundedness | 1.0 | 1.0 |
| Faithfulness | 1.0 | 1.0 |
| Hallucination rate | 0.0 | 0.0 |
| Average context relevance | 0.60 | 0.26 |

The lower context-relevance score after chunking is documented as a trade-off:
the system retrieves a broader set of policy provisions, including exclusions,
sub-limits, and day-care sections that may not repeat the exact procedure
keyword.

### Operational features

The current implementation includes:

- FastAPI health and metrics endpoints;
- Celery and Redis deployment path;
- local synchronous fallback;
- Prometheus metrics;
- Grafana dashboard configuration;
- result caching;
- per-client rate limiting;
- circuit-breaker implementation;
- prompt versions;
- feedback endpoint and summary;
- ingestion manifest;
- Docker health checks;
- runbook and incident log;
- presentation-ready traces for five canonical scenarios.

### Measured Docker load results

The final five-user Locust runs completed with zero failures:

| Deployment | Requests | Failures | Aggregate RPS | p50 | p95 |
|---|---:|---:|---:|---:|---:|
| 1 worker | 245 | 0 | 4.18 | 31 ms | 54 ms |
| 3 workers | 295 | 0 | 5.04 | 33 ms | 55 ms |

The three-worker run produced approximately 20.5% higher observed throughput.
The workload did not saturate the worker pool, so this is evidence of modest
scaling under the tested workload, not a maximum-capacity claim. Locust
statistics aggregate the individual HTTP requests in the submit-and-poll
lifecycle rather than one combined end-to-end timer.

---

## 7. How to Run the Demonstration

### Docker path

```powershell
copy .env.example .env
docker compose up --build
Invoke-RestMethod http://localhost:8000/health
```

Open:

- Swagger: `http://localhost:8000/docs`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`

### Local test path

```powershell
python -m pytest -q
python -m eval.evaluate_rag --report results\evaluation.json
python -m src.agents.trace_formatter
```

### Load-test path

```powershell
locust -f load_test\locustfile.py `
  --host http://localhost:8000 `
  --headless -u 5 -r 1 -t 1m
```

For worker scaling:

```powershell
docker compose up --scale worker=3
```

The measured baseline and scaled results are documented in
[REPORT.md](./REPORT.md). Re-run Locust if the presentation environment
changes.

---

## 8. Strengths of the Current Implementation

- The difficult cataract waiting-period case is explicitly handled.
- The workflow retrieves both coverage and modifying provisions.
- The system is conservative when evidence is missing.
- Citation grounding is checked before returning an answer.
- Invalid requests are quarantined before workflow execution.
- The workflow is deterministic and reproducible.
- The agent responsibilities, hand-offs, retries, and escalation paths are
  explicit and test-covered.
- Presentation traces make the workflow transitions inspectable during review.
- The API preserves rate limiting while allowing distinct Docker load-test
  clients through `X-Client-ID`.
- The repository includes tests, evaluation data, deployment files, a report,
  runbook, and incident log.
- The implementation is lightweight enough to run locally without paid model
  APIs.

---

## 9. Known Limitations to Explain Honestly

- Retrieval uses deterministic token overlap rather than FAISS/Chroma
  embeddings.
- The orchestration is a hand-written state graph rather than LangGraph or
  CrewAI.
- The decision workflow does not depend on a live LLM provider.
- The corpus is limited and contains illustrative policy documents.
- Results use JSON persistence rather than a production database.
- OpenTelemetry export to Jaeger or Grafana Tempo is not implemented.
- The recorded Docker and multi-worker results are measured evidence from the
  tested environment; they should be re-run if the presentation machine or
  workload changes.
- Authentication and authorization are not implemented.

These are appropriate topics for the “limitations and future work” portion of
the review. They do not invalidate the demonstrated prototype, but they
should not be claimed as fully implemented requirements.

---

## 10. Suggested Review Explanation

### One-minute explanation

> Our project is a health-insurance pre-authorisation desk. The problem is that
> coverage, exclusions, waiting periods, and limits may be written in different
> sections of a policy, so a simple search can give the wrong answer. Our
> system validates the request, classifies the treatment, performs multiple
> policy searches, applies deterministic coverage rules, verifies that every
> citation supports the result, and escalates when it cannot safely decide.
> The key demonstration is cataract surgery after 11 months: although cataract
> surgery is covered, the separate 24-month waiting-period clause prevents an
> approval. Our 25-case evaluation passed all cases with groundedness and
> faithfulness of 1.0 and zero measured hallucinations. The implementation
> also has explicit agent hand-offs, bounded tool execution, verification
> retry, and measured Docker load-test evidence.

### If asked why no LangGraph or vector database is used

> We chose a lightweight deterministic state graph and token-overlap index to
> keep the academic prototype reproducible, dependency-light, and auditable.
> The implementation still demonstrates distinct workflow responsibilities,
> callable retrieval tools, bounded execution, verification, retries, and
> conservative escalation. LangGraph and embedding-based retrieval are
> identified as production or future upgrades rather than hidden claims.

### If asked whether the system authorises treatment

> No. It only produces a coverage recommendation with evidence. A medical or
> insurance officer remains responsible for the final decision.

