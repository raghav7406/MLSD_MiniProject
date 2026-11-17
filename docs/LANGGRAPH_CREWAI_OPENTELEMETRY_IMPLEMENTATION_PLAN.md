# Semantic Retrieval, LangGraph, and OpenTelemetry/Jaeger Implementation Plan

## Status and purpose

This is the implementation plan for the remaining required capabilities:
semantic policy retrieval, LangGraph orchestration, and OpenTelemetry tracing
with Jaeger. None of these capabilities is currently implemented.

The current deterministic workflow remains the baseline and rollback target:

- hand-written bounded graph in `src/agents/graph.py`;
- `ClinicalAgent`, `CoverageAgent`, and `VerificationAgent`;
- centralized tools in `src/agents/tools.py`;
- token-overlap retrieval;
- Prometheus metrics and `run_id`/`correlation_id` reconstruction;
- Celery/Redis execution through Docker Compose.

The implementation must preserve the existing response contract and safety
behavior before any presentation claim changes. LangGraph is the selected
orchestration framework; CrewAI is not part of the target implementation.

---

## 1. Goals and non-goals

### Goals

1. Replace lexical token-overlap retrieval with semantic similarity search
   while retaining clause identifiers and source metadata.
2. Represent the existing workflow in LangGraph without weakening
   deterministic policy rules.
3. Preserve bounded execution, explicit hand-offs, tool limits, verification,
   retry, and conservative escalation.
4. Emit distributed traces across API submission, Celery execution, Redis
   transport, agent nodes, tool calls, verification retry, and persistence.
5. Make traces searchable in Jaeger using `run_id` and `correlation_id`.
6. Add automated evidence that the new path produces the same decisions as the
   current path.

### Non-goals

- Do not add a live LLM to the decision path merely to satisfy a framework
  dependency.
- Do not implement both LangGraph and CrewAI. LangGraph is the selected
  framework and CrewAI is explicitly out of scope.
- Do not remove JSON persistence, Prometheus, or the existing API.
- Do not treat token-overlap retrieval as the final retrieval implementation;
  it remains only as a rollback path during migration.
- Do not record request payloads, policy text, credentials, or patient
  identifiers in traces.

---

## 2. Current architecture to preserve

The migration starts from this workflow:

```text
FastAPI validation and guardrails
    ↓
Celery task through Redis
    ↓
Input guardrail
    ↓
Clinical / Intake Agent
    ↓
Coverage / Decision Agent
    ├── corpus_search
    ├── clause_lookup
    └── request_field_lookup
    ↓
Verification Agent
    ├── final response when grounded
    └── alternate search once, then safe escalation
    ↓
Atomic JSON result persistence
```

The current state contract in `src/agents/state.py` already contains the
important migration fields:

- request and identifiers;
- classification flags;
- retrieved clauses and citations;
- recommendation and route;
- verification attempts and issues;
- steps, tool calls, deadlines, and timings;
- trace events, prompt version, token usage, and cost.

The framework adapter must map to this contract rather than introduce a
second incompatible response model.

---

## 3. Framework decision

### Recommended primary choice: LangGraph

LangGraph is the lower-risk fit because the current implementation is already
a typed, conditional state graph. The migration can map:

| Current concept | LangGraph representation |
|---|---|
| `AgentState` | Graph state schema |
| `run_workflow` | Compiled graph invocation |
| Named route functions | Conditional edges |
| Clinical/Coverage/Verification classes | Graph nodes |
| `execute_tool` | Bound graph tools or node calls |
| Verification retry | Conditional alternate-search edge |
| Step/tool/deadline bounds | Explicit state checks and runtime callbacks |
| `PreAuthResponse` | Final response adapter |

LangGraph is mandatory for the target implementation because the current
workflow already has typed shared state, named nodes, conditional routing, and
verification retry. Nodes may continue to call deterministic business logic;
a live model is not required for the first compliant implementation.

---

## 4. Target architecture

```text
Client
  ↓
FastAPI span: preauth.submit
  ↓
Celery producer span ── Redis messaging ── Celery worker consumer span
  ↓
LangGraph workflow span: preauth.workflow
  ├── guardrail span
  ├── clinical_agent span
  ├── coverage_agent span
  │     └── tool spans: corpus_search / clause_lookup / field_lookup
  ├── verification_agent span
  ├── alternate_search span (conditional)
  └── result_persistence span
  ↓
Jaeger UI
```

Prometheus remains responsible for aggregate counters and histograms.
OpenTelemetry/Jaeger provides per-run distributed traces; it does not replace
Prometheus.

---

## 5. Implementation phases

### Phase 0 - Baseline and branch protection

1. Create a dedicated branch for the experiment.
2. Capture the current baseline:
   - `python -m pytest -q`;
   - 25-case evaluation output;
   - one 11-month cataract result;
   - one 24-month cataract result;
   - one unsupported-procedure trace;
   - one verification-retry trace.
3. Freeze the current response schema and route values.
4. Add a feature flag such as `AGENT_RUNTIME=legacy|langgraph`, defaulting to
   `legacy` during migration.
5. Confirm the legacy path remains the rollback target if the framework import
   or runtime fails.

**Exit criteria:** the baseline passes unchanged and the migration has a
reproducible comparison target.

### Phase 1 - Semantic retrieval and index migration

Replace token-overlap retrieval with an embedding-backed semantic index.

1. Keep the existing chunk boundaries, clause IDs, source, page, and chunk
   metadata.
2. Select one embedding model that can run in the Docker environment without
   an external API key. Record its version and embedding dimension.
3. Implement an embedding provider interface so the model can be replaced
   without changing the Coverage Agent.
4. Build a FAISS or Chroma index during ingestion and persist the index plus a
   manifest containing:
   - corpus file hashes;
   - embedding model/version;
   - vector dimension;
   - chunk count;
   - build timestamp.
5. Add semantic similarity search with a configurable `top_k` and minimum
   similarity threshold.
6. Keep exact `clause_lookup` for identifiers such as `Code-Excl02`; semantic
   search must complement, not replace, deterministic clause lookup.
7. Preserve a deterministic lexical fallback for index/model failures, but
   mark the fallback in tool metadata and do not silently present it as
   semantic retrieval.
8. Add evaluation cases containing paraphrases and synonyms that token overlap
   would miss.

The Coverage Agent must continue to perform separate searches for base
coverage, exclusions/waiting periods, sub-limits, and day-care eligibility.
Only the retrieval implementation changes; policy rules remain authoritative.

**Exit criteria:** semantic retrieval returns the expected clauses for direct
wording and paraphrased queries, every result retains citation metadata, the
index rebuild is reproducible, and the 25-case evaluation does not regress.

### Phase 2 - Dependency and configuration isolation

Add only the selected framework and tracing packages to the dependency
manifest. Recommended OpenTelemetry packages are:

- `opentelemetry-api`;
- `opentelemetry-sdk`;
- `opentelemetry-exporter-otlp-proto-grpc` or HTTP;
- `opentelemetry-instrumentation-fastapi`;
- `opentelemetry-instrumentation-celery`;
- `opentelemetry-instrumentation-redis`.

Add LangGraph and its compatible dependencies. Do not add CrewAI.

Add configuration with safe local defaults:

```text
AGENT_RUNTIME=legacy
SEMANTIC_RETRIEVAL_ENABLED=false
EMBEDDING_MODEL=
VECTOR_INDEX_PATH=data/semantic_index
OTEL_ENABLED=false
OTEL_SERVICE_NAME=preauth-api
OTEL_EXPORTER_OTLP_ENDPOINT=
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=1.0
```

Requirements:

- `OTEL_ENABLED=false` must work without Jaeger or an exporter.
- no API keys or secrets are required for deterministic mode;
- package versions must be pinned or upper-bounded after compatibility
  testing;
- Python versions supported by the repository must remain installable.

**Exit criteria:** clean install, legacy tests pass, the semantic index can be
built, and the application starts with tracing disabled.

### Phase 3 - OpenTelemetry foundation

Create a small tracing module, for example
`src/observability/tracing.py`, responsible for:

1. Creating a `TracerProvider` only once per process.
2. Installing a resource with service name and environment.
3. Configuring an OTLP exporter only when enabled and configured.
4. Using a console or no-op exporter for local tests.
5. Providing helpers:
   - `get_tracer()`;
   - `set_run_context(run_id, correlation_id)`;
   - `record_exception(span, error)`;
   - `shutdown_tracing()`.
6. Avoiding duplicate provider initialization during Uvicorn reloads and
   Celery worker forks.

Instrument these boundaries first:

- FastAPI request handling;
- Celery task producer and worker;
- Redis transport if instrumentation is compatible with the selected Redis
  client;
- workflow and tool spans.

Recommended span names:

```text
preauth.submit
preauth.poll
preauth.feedback
preauth.workflow
preauth.guardrail
preauth.agent.clinical
preauth.agent.coverage
preauth.agent.verification
preauth.verification.retry
preauth.tool.corpus_search
preauth.tool.clause_lookup
preauth.tool.request_field_lookup
preauth.result.persist
```

Recommended low-cardinality attributes:

| Attribute | Example | Rule |
|---|---|---|
| `preauth.run_id` | UUID | Required; never use full request data |
| `preauth.correlation_id` | UUID | Required |
| `preauth.agent` | `coverage` | Fixed vocabulary |
| `preauth.tool` | `corpus_search` | Fixed vocabulary |
| `preauth.route` | `medical-review` | Record on completed workflow |
| `preauth.recommendation` | `QUERY` | Record on completed workflow |
| `preauth.verification_passed` | `false` | Boolean |
| `preauth.verification_attempt` | `2` | Integer |
| `preauth.escalation_required` | `true` | Boolean |
| `preauth.error_type` | `TimeoutError` | Type only, no raw payload |

Never attach diagnosis text, procedure text, member IDs, policy numbers,
citations containing policy text, request JSON, authorization headers, or
Redis payloads to spans. Hashing an identifier is not automatically safe if
the identifier is reversible or linkable; prefer the existing run ID.

**Exit criteria:** a local workflow produces a trace with the same run ID as
the API result, and tracing-disabled mode behaves identically.

### Phase 4 - LangGraph adapter

Implement a separate adapter, for example
`src/agents/langgraph_runtime.py`.

1. Define the graph state as a typed state compatible with `AgentState`.
2. Add nodes:
   - `guardrail_node`;
   - `clinical_node`;
   - `coverage_node`;
   - `verification_node`;
   - `alternate_search_node`;
   - `final_response_node`;
   - escalation result nodes as needed.
3. Reuse existing agent classes and `execute_tool`.
4. Implement conditional edges using the current routing rules.
5. Enforce bounds before and after each node:
   - maximum 10 steps;
   - maximum 20 tool calls;
   - 30-second deadline.
6. Convert the final state through the existing
   `PreAuthResponse` construction path.
7. Add one workflow span around the graph and child spans around nodes/tools.
8. Keep framework exceptions explicit; on failure, return the standard safe
   escalation response and record the exception span.

Do not expose a generic agent loop that can call arbitrary tools. Every tool
call must go through the existing centralized runner.

**Exit criteria:** LangGraph mode produces byte-for-byte equivalent decision
fields for the baseline cases, with additional trace metadata allowed, and
uses the semantic retrieval tools.

### Phase 5 - Celery and context propagation

1. Propagate the W3C trace context from the FastAPI submission span into the
   Celery task headers.
2. Extract the context in the worker before starting `preauth.workflow`.
3. Set `run_id` and `correlation_id` as span attributes and structured-log
   fields.
4. Verify that API, producer, worker, workflow, tool, and persistence spans
   appear in one Jaeger trace.
5. Verify polling creates a separate child/linked trace without duplicating
   the original workflow.
6. Ensure trace export failures never fail a preauth request.

If automatic Celery instrumentation cannot preserve context reliably, use
explicit propagation through task headers and document that implementation.

**Exit criteria:** one Docker request can be found in Jaeger by run ID and
contains API-to-worker-to-tool timing.

### Phase 6 - Jaeger and Docker Compose

Add a Jaeger service only after local tracing works:

```yaml
jaeger:
  image: jaegertracing/all-in-one:<pinned-version>
  ports:
    - "16686:16686"
    - "4317:4317"
    - "4318:4318"
  environment:
    COLLECTOR_OTLP_ENABLED: "true"
```

Configure `app` and `worker` with the same OTLP endpoint, for example
`http://jaeger:4317`. Do not expose the OTLP collector port publicly in a
production deployment without network controls.

Preferred production topology:

```text
app/worker → OpenTelemetry Collector → Jaeger
```

The Collector is optional for the first demonstration because it adds another
service. Add it when batching, filtering, retries, multi-exporter routing, or
production retention is required.

Add health/readiness checks and verify startup with tracing disabled and
enabled. Keep Jaeger data ephemeral for the academic demo unless a volume is
explicitly required.

**Exit criteria:** `docker compose up --build` starts the stack with tracing
enabled, Jaeger is reachable at `http://localhost:16686`, and the API remains
healthy if Jaeger is stopped.

### Phase 7 - Tests and parity evidence

Add focused tests:

1. **Runtime selection**
   - legacy is the default;
   - LangGraph adapter loads;
   - unavailable LangGraph runtime fails explicitly or falls back according to
     the configured policy.
2. **Semantic retrieval**
   - direct wording and paraphrased queries retrieve the expected clauses;
   - similarity thresholds and top-k behavior are deterministic;
   - source, page, and clause metadata survive retrieval;
   - lexical fallback is observable and never mislabeled as semantic.
3. **Decision parity**
   - 11-month cataract → `REJECT`, `medical-review`;
   - 24-month cataract → `APPROVE`, `approve-recommended`;
   - malformed request → HTTP 422 and quarantine;
   - unsupported procedure → `QUERY`, `medical-review`;
   - prompt injection → guardrail route;
   - verification failure → alternate search then escalation;
   - tool failure, timeout, deadline, and tool-call limit → safe escalation.
4. **Trace behavior**
   - spans contain run/correlation IDs;
   - expected parent-child relationships exist;
   - sensitive fields are absent;
   - exporter failure does not alter the response;
   - disabled tracing does not require Jaeger.
5. **Docker smoke test**
   - API and worker start;
   - one request reaches Jaeger;
   - `/health`, `/metrics`, feedback, and polling remain available.

Run:

```powershell
python -m pytest -q
python -m eval.evaluate_rag --report results\evaluation.json
docker compose config
```

The 25-case evaluation must remain 25/25 with groundedness, faithfulness,
and hallucination results unchanged from the baseline unless a deliberate
behavior change is separately approved.

### Phase 8 - Performance and operational validation

Measure tracing overhead rather than assuming it is negligible:

1. Run the existing five-user Locust profile with tracing disabled.
2. Run the same profile with tracing enabled and Jaeger available.
3. Compare request p50, p95, RPS, failures, and workflow latency.
4. Repeat with one and three workers.
5. Test Jaeger unavailable and exporter timeout scenarios.

Acceptance target:

- no request failures caused by tracing;
- p95 remains below the declared two-second SLO;
- any measurable overhead is reported;
- trace export is asynchronous or bounded so it cannot block the decision
  workflow;
- queue and worker scaling conclusions are kept separate from trace-storage
  capacity.

---

## 6. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Dependency conflicts or Python-version incompatibility | Isolate the adapter, pin compatible versions, retain legacy runtime |
| Framework changes decision behavior | Reuse existing agents/tools and enforce parity tests |
| LLM introduces nondeterminism | Keep deterministic rules authoritative; do not require a live model |
| Trace exporter blocks requests | Batch/asynchronous export, short timeout, fail-open behavior |
| Sensitive policy/member data leaks into Jaeger | Attribute allowlist, redaction tests, no payload recording |
| Celery trace context is lost | Explicit W3C header propagation and Docker smoke test |
| Jaeger becomes a runtime dependency | Optional exporter and graceful degradation |
| Duplicate spans from reload/fork | One provider per process and worker initialization hooks |
| High-cardinality metrics or span attributes | Fixed vocabularies and run ID only |
| LangGraph changes decision behavior | Reuse existing agents/tools and enforce parity tests |

---

## 7. Rollback and release strategy

1. Keep `AGENT_RUNTIME=legacy` as the default until parity and load tests pass.
2. Keep `OTEL_ENABLED=false` as the safe local default.
3. Enable the new runtime only in a dedicated Compose profile or environment
   override during validation.
4. Roll back by setting `AGENT_RUNTIME=legacy` and
   `OTEL_ENABLED=false`; no data migration should be required.
5. Do not remove the hand-written graph until the new path has passed at
   least one complete presentation run and the evaluator confirms the named
   framework requirement.

---

## 8. Presentation evidence to collect

Collect the following evidence before claiming completion:

1. A LangGraph graph screenshot with the selected framework clearly visible.
2. A Jaeger trace searched by `run_id`.
3. The trace showing:
   - API submission;
   - Celery worker execution;
   - clinical, coverage, and verification spans;
   - tool calls;
   - verification retry or escalation;
   - atomic result persistence.
4. A screenshot or export proving sensitive request fields are absent.
5. Baseline-versus-enabled tracing latency and failure results.
6. The 25-case evaluation output and focused parity-test output.
7. A failure demonstration showing the application still returns safe
   behavior when Jaeger is unavailable.

Do not claim distributed tracing merely because a Jaeger container is running;
the trace must contain a real end-to-end request with the expected spans.

---

## 9. Definition of done

The implementation is complete only when:

- LangGraph is selected and its dependency versions are reproducible;
- semantic retrieval is enabled, indexed, evaluated, and retains citation
  metadata;
- legacy mode remains available and is the documented rollback;
- all existing safety, routing, verification, and response-contract tests pass;
- the 25-case evaluation remains unchanged or differences are explained;
- API-to-worker-to-tool traces are visible in Jaeger using `run_id`;
- sensitive input and policy content are absent from trace attributes;
- Jaeger/exporter failure does not fail or approve a preauth request;
- tracing-disabled mode works without Jaeger;
- tracing overhead is measured against the two-second SLO;
- Docker Compose starts the validated topology;
- the presentation evidence listed above has been captured;
- only then should the main README, report, and runbook be updated to claim
  the feature.
