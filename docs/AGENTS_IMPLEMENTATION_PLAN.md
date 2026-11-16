# Agent Architecture Implementation Plan

## 1. Objective

Strengthen the current pre-authorisation workflow so that the agent
architecture is explicit, demonstrable, testable, and aligned with the PDF
requirements:

- at least two agents with distinct responsibilities;
- retrieval exposed as callable tools;
- bounded execution;
- verification before returning an answer;
- alternate search and escalation when verification fails;
- clear hand-offs and failure behavior;
- reconstructible run metadata for presentation.

The current implementation already has most of these behaviors in a
hand-written state graph. This plan focuses on making the architecture
explicit and presentation-ready without destabilising the working product.

## 2. Current Implementation

Current agent components:

| Component | Current responsibility |
|---|---|
| `clinical_agent.py` | Classifies the clinical category and flags exclusions, day-care, and pre-existing conditions |
| `coverage_agent.py` | Performs coverage, exclusion, sub-limit, day-care, and clause retrieval, then applies rules |
| `verification.py` | Checks citation grounding and recommendation consistency |
| `tools.py` | Provides corpus search, clause lookup, and request-field lookup |
| `graph.py` | Coordinates guardrails, classification, coverage, verification, retry, and final response construction |
| `state.py` | Stores request, retrieved clauses, tool calls, timings, limits, and verification state |

The current workflow is intentionally deterministic and does not depend on a
live LLM provider. This is useful for reproducible evaluation and a stable
presentation demo.

## 3. Requirement Mapping

| Requirement | Planned evidence |
|---|---|
| Two distinct agents | Clinical/Intake Agent and Coverage/Decision Agent with separate modules and state hand-off |
| Verification | Dedicated Verification Agent with grounding and consistency checks |
| Three tools | `corpus_search`, `clause_lookup`, and `request_field_lookup` |
| Agent hand-off | Explicit state fields and graph transitions |
| Retrieval as a tool | Coverage and verification nodes call tools through a shared tool interface |
| Bounded execution | Maximum steps, tool calls, and wall-clock deadline |
| Retry | Alternate verification search followed by escalation |
| Safe failure | Query or medical-review route when evidence is missing or conflicting |
| Reconstruction | Run ID, tool calls, queries, result counts, timings, verification attempts, and outcome metadata |

## 4. Recommended Approach

### Preferred first step: improve the existing graph

Do not immediately replace the current workflow with LangGraph or CrewAI.
The existing graph already demonstrates the required behavior and currently
passes the workflow and evaluation tests.

First make the existing architecture clearer:

1. Define explicit agent interfaces.
2. Define explicit graph transitions.
3. Record hand-offs and tool calls.
4. Add focused tests for each transition and failure path.
5. Add a trace formatter for the live demonstration.

This is the lowest-risk path.

### Optional strict-compliance step

If the evaluator specifically requires the name **LangGraph** or **CrewAI**,
add a thin adapter around the existing functions rather than rewriting the
business rules.

The framework graph should call the existing:

- `classify_clinical_request`;
- `verify_coverage`;
- `verify_decision`;
- guardrail functions;
- retrieval tools.

The framework should orchestrate the workflow, not duplicate the policy
logic.

## 5. Target Architecture

```text
PreAuthRequest
      |
      v
Input Guardrail Node
      |
      v
Clinical / Intake Agent
      |
      | AgentState hand-off:
      | category, flags, extracted entities
      v
Coverage / Decision Agent
      |
      | Tool calls:
      | corpus_search
      | clause_lookup
      | request_field_lookup
      v
Verification Agent
      |
      +-- verified --> Final Response
      |
      +-- unsupported evidence --> Alternate Search
                                  |
                                  +-- verified --> Final Response
                                  +-- failed --> Medical Review / Query
```

### Agent responsibilities

#### Clinical / Intake Agent

Input:

- diagnosis;
- procedure;
- admission type;
- pre-existing-condition fields.

Output:

- clinical category;
- admission classification;
- day-care flag;
- exclusion flag;
- pre-existing-condition flag;
- unsupported-category flag;
- classification timing.

It must not decide coverage or approval.

#### Coverage / Decision Agent

Input:

- validated request;
- classification output;
- risk flags.

Responsibilities:

- choose the relevant retrieval tools;
- retrieve coverage and modifying provisions;
- retrieve waiting periods and exclusions separately;
- apply deterministic rules;
- produce a provisional recommendation and citations.

It must not return an unverified final answer.

#### Verification Agent

Responsibilities:

- verify every citation against retrieved text;
- verify that approval has supporting evidence;
- verify that unsupported, excluded, or early pre-existing cases are not
  approved;
- check that the final route matches the recommendation;
- request one alternate search when evidence is incomplete;
- escalate after the retry fails.

## 6. State Contract

Extend `AgentState` only where necessary. The state should contain:

```text
run_id
correlation_id
request
clinical_category
admission_classification
is_daycare
is_unsupported
has_pre_existing
retrieved_clauses
base_clauses
exclusion_clauses
sublimit_clauses
citations
recommendation
route
reason
indicative_limit
escalation_required
verification_passed
verification_attempts
verification_issues
tool_calls
total_tool_calls
step_timings
steps
max_steps
max_tool_calls
deadline_seconds
prompt_version
token_usage
cost_usd
fallback_used
error
```

Each tool call should record:

- tool name;
- query or lookup key;
- input purpose;
- result count;
- duration;
- success/failure;
- retry number;
- run ID.

## 7. Tool Interface

Keep the current tools, but define a common result shape:

```python
{
    "tool": "corpus_search",
    "query": "...",
    "results": [...],
    "result_count": 3,
    "duration_seconds": 0.002,
    "success": True,
    "error": None,
}
```

Required tools:

1. `corpus_search(query, top_k)`
2. `clause_lookup(clause_id)`
3. `request_field_lookup(state, field)`

The tools must:

- have bounded execution time;
- return explicit errors;
- avoid silently returning fabricated or empty success values;
- preserve source, page, clause ID, and text;
- increment the run's tool-call count.

## 8. Graph Transitions and Bounds

Implement or document these transitions:

```text
guardrail
  -> escalation if injection/toxicity is detected
  -> clinical otherwise

clinical
  -> coverage

coverage
  -> verification
  -> escalation if a hard bound is reached

verification
  -> final response if verified
  -> alternate search on first verification failure
  -> escalation after failed retry
```

Required limits:

- maximum steps: 10;
- maximum tool calls: 20;
- total deadline: 30 seconds;
- at most one alternate verification search;
- no confident response after timeout or incomplete execution.

All bound failures must produce a query or medical-review response with a
reason and `verification_passed = false`.

## 9. Failure and Escalation Matrix

| Situation | Expected action |
|---|---|
| Prompt injection detected | Stop before clinical/coverage decisions; medical review |
| Permanent exclusion detected | Query/medical review with exclusion explanation |
| Unsupported clinical category | Query/medical review; never approve |
| Pre-existing condition below 48 months | Medical review |
| No retrieved clauses | Query to hospital |
| Conflicting clauses | Medical review |
| Citation not grounded | Alternate search, then medical review |
| Approval without citations | Alternate search, then medical review |
| Tool timeout | Retry within bounds, then query/medical review |
| Maximum steps/tool calls exceeded | Query/medical review |
| Unexpected workflow exception | Failed/escalated result, never approval |

## 10. Implementation Phases

### Phase 1 - Stabilise agent contracts

Tasks:

- Add typed agent input/output protocols or helper models.
- Separate provisional decision data from final response data.
- Make the clinical-to-coverage hand-off explicit.
- Add `agent_name`, `agent_status`, and `handoff_reason` to trace metadata.

Exit criteria:

- Clinical agent cannot directly return an approval.
- Coverage agent cannot bypass verification.
- Existing tests still pass.

### Phase 2 - Centralise tool execution

Tasks:

- Add a shared tool runner that records calls and timings.
- Enforce tool-call limits in one place.
- Add tool timeout handling.
- Return explicit tool errors.
- Replace direct retrieval calls in agent modules with the tool runner.

Exit criteria:

- Every retrieval call appears in `metadata.tool_calls`.
- Tool-call count matches the actual calls.
- A simulated tool failure produces escalation.

### Phase 3 - Make graph routing explicit

Tasks:

- Introduce named transition functions:
  - `route_after_guardrail`;
  - `route_after_clinical`;
  - `route_after_coverage`;
  - `route_after_verification`.
- Record each node's start/end time and status.
- Record the reason for every transition.
- Preserve the current deterministic policy rules.

Exit criteria:

- A trace clearly shows the nodes and transitions.
- Cataract 11-month and 24-month cases follow different decision paths.
- Unsupported and injection cases stop at the correct point.

### Phase 4 - Add verification demonstrations

Tasks:

- Add a test that injects an unsupported citation.
- Confirm the first verification attempt fails.
- Confirm alternate search runs.
- Confirm the final response escalates if grounding remains invalid.
- Add a test for approval without citations.
- Add a test for a simulated tool timeout.

Exit criteria:

- No unverified answer is returned.
- Retry and escalation are visible in metadata.
- Demonstration output includes the verification issue.

### Phase 5 - Optional LangGraph adapter

Only perform this phase if the evaluator requires the library explicitly.

Tasks:

- Add LangGraph to the dependency manifest.
- Create a graph adapter module.
- Represent each existing agent/node as a framework node.
- Use conditional edges for guardrail, retry, and escalation routes.
- Keep policy rules and retrieval tools in the existing modules.
- Add a feature flag for the adapter if both implementations must be
  preserved.
- Run the complete test suite under both modes if possible.

Exit criteria:

- The LangGraph path produces the same response contract.
- Existing 25-case evaluation remains unchanged.
- Docker build succeeds from a clean clone.
- No increase in false approvals or ungrounded citations.

## 11. Test Plan

### Unit tests

- Clinical classification for each supported category.
- Exclusion detection.
- Day-care detection.
- Pre-existing-condition flagging.
- Each retrieval tool.
- Tool-call recording.
- Tool timeout and error handling.
- Bound checks.
- Route transitions.

### Workflow tests

- Cataract at 11 months: reject/escalate with waiting-period evidence.
- Cataract at 24 months: approve recommendation with citations.
- Unsupported procedure: medical review.
- Prompt injection: guardrail stop.
- Pre-existing condition before 48 months: medical review.
- No clauses: query to hospital.
- Ungrounded citation: retry then escalation.
- Approval with no citation: escalation.
- Maximum tool calls: escalation.
- Deadline exceeded: escalation.

### Regression tests

```powershell
python -m pytest -q
python -m eval.evaluate_rag --report results\evaluation.json
```

Required invariant:

- 25-case accuracy must remain 1.0 unless a deliberate behavior change is
  documented.
- Groundedness must remain 1.0.
- Hallucination rate must remain 0.0.

## 12. Presentation Evidence

Prepare one JSON trace or formatted console output for each:

1. Cataract at 11 months:
   - clinical classification;
   - coverage search;
   - Code-Excl02 lookup;
   - verification;
   - rejection/medical-review route.
2. Cataract at 24 months:
   - waiting period satisfied;
   - sub-limit applied;
   - approval recommendation;
   - citations verified.
3. Unsupported procedure:
   - unsupported flag;
   - escalation;
   - no fabricated answer.
4. Prompt injection:
   - guardrail match;
   - workflow stopped;
   - medical-review route.
5. Verification failure:
   - first failure;
   - alternate search;
   - final verification result or escalation.

The reviewer should be able to see:

- agent names;
- hand-off state;
- tool name and query;
- retrieved passage IDs;
- verification outcome;
- final route;
- run ID.

## 13. Scope and Risk Guidance

### Low-risk changes

- More explicit metadata.
- Shared tool-call recorder.
- Named routing functions.
- Additional tests.
- Trace formatting.
- Documentation.

### Medium-risk changes

- Tool timeout wrappers.
- Persistent event records.
- Altering retry behavior.
- Changing response metadata.

### High-risk changes

- Replacing the current graph with LangGraph/CrewAI.
- Introducing live LLM decisions.
- Replacing deterministic retrieval.
- Changing recommendation rules.

Do the low-risk work first. Only proceed to framework replacement if the
evaluator explicitly requires it. Create a separate branch before any
high-risk dependency or orchestration change.

## 14. Definition of Done

The agent implementation is ready for review when:

- two distinct agents and the verification agent are documented and visible;
- all three tools are callable and recorded;
- graph transitions and hand-offs are explicit;
- execution limits are enforced;
- verification retry and escalation are demonstrable;
- no timeout, tool failure, unsupported case, or ungrounded answer becomes a
  confident approval;
- run metadata reconstructs the complete agent path;
- all tests and the 25-case evaluation pass;
- Docker Compose still starts successfully;
- the presentation has saved traces for the required cases.
