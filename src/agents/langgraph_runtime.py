"""
LangGraph runtime adapter for the PreAuth multi-agent decision pipeline.

Implements a compiled StateGraph matching the agent topology:
- guardrail -> clinical -> coverage -> verification -> [alternate_search] -> final / escalate

Enforces:
- Hard bounds (10 steps, 20 tools, 30s deadline)
- OpenTelemetry span hierarchy (preauth.workflow, preauth.agent.*)
- Exact parity with the legacy workflow engine
- Backward-compatible PreAuthResponse emission
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from data_contracts import (
    PreAuthRequest,
    PreAuthResponse,
    Recommendation,
    Route,
    recommendation_to_route,
)
from src.agents.clinical_agent import ClinicalAgent, classify_clinical_request
from src.agents.coverage_agent import CoverageAgent, verify_coverage
from src.agents.graph import MAX_STEPS, MAX_TOOL_CALLS, DEADLINE_SECONDS, _build_response, _build_timeout_response
from src.agents.state import AgentState, TraceEvent
from src.agents.verification import VerificationAgent, verify_decision
from src.observability.tracing import record_exception, trace_span


def _check_bounds(state: AgentState) -> str | None:
    """Check if any hard execution limit has been breached."""
    if state.get("steps", 0) >= state.get("max_steps", MAX_STEPS):
        return f"Maximum steps exceeded ({state.get('steps', 0)}/{state.get('max_steps', MAX_STEPS)})"
    if state.get("total_tool_calls", 0) >= state.get("max_tool_calls", MAX_TOOL_CALLS):
        return f"Maximum tool calls exceeded ({state.get('total_tool_calls', 0)}/{state.get('max_tool_calls', MAX_TOOL_CALLS)})"
    elapsed = time.time() - state.get("start_time", time.time())
    if elapsed > state.get("deadline_seconds", DEADLINE_SECONDS):
        return f"Execution deadline exceeded ({elapsed:.2f}s > {state.get('deadline_seconds', DEADLINE_SECONDS)}s)"
    return None


def _log_trace_event(
    state: AgentState,
    node: str,
    agent_name: str,
    agent_status: str,
    transition_to: str,
    handoff_reason: str,
    duration: float,
) -> None:
    """Record an explicit graph transition event in the state's trace log."""
    events = state.setdefault("trace_events", [])
    event: TraceEvent = {
        "step_number": len(events) + 1,
        "node": node,
        "agent_name": agent_name,
        "agent_status": agent_status,
        "transition_to": transition_to,
        "handoff_reason": handoff_reason,
        "duration_seconds": round(duration, 4),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    events.append(event)


# --- Node Definitions ----------------------------------------------------------

def guardrail_node(state: AgentState) -> dict[str, Any]:
    """Execute input security and prompt safety validations."""
    bound_err = _check_bounds(state)
    if bound_err:
        state["error"] = f"bound_breach: {bound_err}"
        state["escalation_required"] = True
        return state

    node_start = time.time()
    run_id = state.get("run_id", "")

    with trace_span("preauth.guardrail", attributes={"preauth.agent": "guardrail", "preauth.run_id": run_id}):
        try:
            from src.guardrails.prompt_guard import check_prompt_injection, check_toxicity
        except ImportError:
            check_prompt_injection = None
            check_toxicity = None

        request = state["request"]
        injection_err = None
        if check_prompt_injection is not None:
            injection_err = check_prompt_injection(
                request.diagnosis_name,
                request.procedure_name,
                getattr(request, "hospital_name", ""),
                getattr(request, "treating_doctor", ""),
            )

        toxicity_err = None
        if check_toxicity is not None and not injection_err:
            toxicity_err = check_toxicity(request.diagnosis_name, request.procedure_name)

        guardrail_err = injection_err or toxicity_err
        guard_duration = time.time() - node_start
        state.setdefault("step_timings", {})["input_guard"] = round(guard_duration, 4)
        state["steps"] = state.get("steps", 0) + 1

        if guardrail_err:
            state["recommendation"] = Recommendation.QUERY.value
            state["reason"] = f"Input rejected by safety guardrail: {guardrail_err}"
            state["escalation_required"] = True
            state["route"] = "medical-review"
            state["indicative_limit"] = 0.0
            state["citations"] = []
            state["verification_passed"] = False
            state["error"] = f"guardrail_rejected: {guardrail_err}"
            _log_trace_event(
                state,
                node="input_guardrails",
                agent_name="Guardrail Node",
                agent_status="REJECTED",
                transition_to="escalate",
                handoff_reason=f"Adversarial or toxic content flagged: {guardrail_err}",
                duration=guard_duration,
            )
        else:
            _log_trace_event(
                state,
                node="input_guardrails",
                agent_name="Guardrail Node",
                agent_status="PASSED",
                transition_to="clinical",
                handoff_reason="Request text passed input safety and injection filters.",
                duration=guard_duration,
            )

    return state


def clinical_node(state: AgentState) -> dict[str, Any]:
    """Execute Clinical / Intake categorization agent."""
    bound_err = _check_bounds(state)
    if bound_err:
        state["error"] = f"bound_breach: {bound_err}"
        state["escalation_required"] = True
        return state

    node_start = time.time()
    run_id = state.get("run_id", "")

    with trace_span("preauth.agent.clinical", attributes={"preauth.agent": "clinical", "preauth.run_id": run_id}):
        try:
            state = classify_clinical_request(state)
            clin_duration = time.time() - node_start
            state["steps"] = state.get("steps", 0) + 1

            _log_trace_event(
                state,
                node="clinical_intake",
                agent_name=ClinicalAgent.name,
                agent_status=state.get("current_status", "COMPLETED"),
                transition_to="coverage",
                handoff_reason=(
                    f"Classified as '{state.get('clinical_category')}', "
                    f"daycare={state.get('is_daycare')}, PED={state.get('has_pre_existing')}. "
                    f"Handoff to Coverage Agent."
                ),
                duration=clin_duration,
            )
        except Exception as exc:
            state["error"] = str(exc)
            state["escalation_required"] = True

    return state


def coverage_node(state: AgentState) -> dict[str, Any]:
    """Execute Coverage / Policy decision agent with centralized tool calls."""
    bound_err = _check_bounds(state)
    if bound_err:
        state["error"] = f"bound_breach: {bound_err}"
        state["escalation_required"] = True
        return state

    node_start = time.time()
    run_id = state.get("run_id", "")

    with trace_span("preauth.agent.coverage", attributes={"preauth.agent": "coverage", "preauth.run_id": run_id}):
        try:
            state = verify_coverage(state)
            cov_duration = time.time() - node_start
            state["steps"] = state.get("steps", 0) + 1

            _log_trace_event(
                state,
                node="coverage_decision",
                agent_name=CoverageAgent.name,
                agent_status=state.get("current_status", "COMPLETED"),
                transition_to="verification",
                handoff_reason=(
                    f"Provisional decision: {state.get('recommendation')} with "
                    f"{len(state.get('citations', []))} citations. Handoff to Verification Agent."
                ),
                duration=cov_duration,
            )
        except Exception as exc:
            state["error"] = str(exc)
            state["escalation_required"] = True

    return state


def verification_node(state: AgentState) -> dict[str, Any]:
    """Execute Verification Agent (Pass 1)."""
    bound_err = _check_bounds(state)
    if bound_err:
        state["error"] = f"bound_breach: {bound_err}"
        state["escalation_required"] = True
        return state

    node_start = time.time()
    run_id = state.get("run_id", "")

    with trace_span("preauth.agent.verification", attributes={"preauth.agent": "verification", "preauth.run_id": run_id}):
        try:
            state = verify_decision(state)
            ver_duration = time.time() - node_start
            state["steps"] = state.get("steps", 0) + 1

            passed = state.get("verification_passed", False)
            _log_trace_event(
                state,
                node="verification_attempt_1",
                agent_name=VerificationAgent.name,
                agent_status="COMPLETED" if passed else "RETRY_REQUESTED",
                transition_to="final" if passed else "alternate_search",
                handoff_reason=(
                    "All citations grounded and provisions verified."
                    if passed
                    else f"Evidence incomplete: {'; '.join(state.get('verification_issues', []))}. Triggering alternate search."
                ),
                duration=ver_duration,
            )
        except Exception as exc:
            state["error"] = str(exc)
            state["escalation_required"] = True

    return state


def alternate_search_node(state: AgentState) -> dict[str, Any]:
    """Execute Verification Retry / Alternate Search."""
    bound_err = _check_bounds(state)
    if bound_err:
        state["error"] = f"bound_breach: {bound_err}"
        state["escalation_required"] = True
        return state

    node_start = time.time()
    run_id = state.get("run_id", "")

    with trace_span("preauth.verification.retry", attributes={"preauth.agent": "verification_retry", "preauth.run_id": run_id}):
        try:
            state = verify_decision(state)
            ver_duration = time.time() - node_start
            state["steps"] = state.get("steps", 0) + 1

            passed = state.get("verification_passed", False)
            _log_trace_event(
                state,
                node="verification_attempt_2",
                agent_name=VerificationAgent.name,
                agent_status="COMPLETED" if passed else "ESCALATED",
                transition_to="final" if passed else "escalate",
                handoff_reason=(
                    "Verification passed after alternate retrieval."
                    if passed
                    else f"Verification failed after retry: {'; '.join(state.get('verification_issues', []))}. Escalated."
                ),
                duration=ver_duration,
            )
        except Exception as exc:
            state["error"] = str(exc)
            state["escalation_required"] = True

    return state


def final_response_node(state: AgentState) -> dict[str, Any]:
    """Execute final grounding verification guardrail."""
    try:
        from src.guardrails.prompt_guard import validate_grounding
    except ImportError:
        validate_grounding = None

    if validate_grounding is not None:
        if not validate_grounding(state.get("citations", []), state.get("retrieved_clauses", [])):
            state["recommendation"] = Recommendation.QUERY.value
            state["reason"] = "Citation grounding guardrail failed; manual review is required."
            state["indicative_limit"] = 0.0
            state["escalation_required"] = True
            state["verification_passed"] = False
            state["route"] = "medical-review"

    return state


def escalation_node(state: AgentState) -> dict[str, Any]:
    """Graceful escalation node when bounds, guardrails, or errors occur."""
    bound_err = _check_bounds(state)
    if bound_err:
        state["reason"] = f"Execution bound reached: {bound_err}. Escalating."
    elif not state.get("reason"):
        state["reason"] = "Workflow escalated for medical review."

    state["recommendation"] = Recommendation.QUERY.value
    state["escalation_required"] = True
    state["route"] = "medical-review"
    state["indicative_limit"] = 0.0
    state["citations"] = []
    state["verification_passed"] = False

    _log_trace_event(
        state,
        node="escalation_node",
        agent_name="Workflow Coordinator",
        agent_status="ESCALATED",
        transition_to="end",
        handoff_reason=state.get("reason", "Escalated for medical review."),
        duration=0.0,
    )
    return state


# --- Routing Conditions --------------------------------------------------------

def route_after_guardrail(state: AgentState) -> Literal["clinical", "escalate"]:
    if state.get("escalation_required") or state.get("error"):
        return "escalate"
    return "clinical"


def route_after_clinical(state: AgentState) -> Literal["coverage", "escalate"]:
    if state.get("error") and not state.get("clinical_category"):
        return "escalate"
    return "coverage"


def route_after_coverage(state: AgentState) -> Literal["verification", "escalate"]:
    if state.get("error"):
        return "escalate"
    return "verification"


def route_after_verification(state: AgentState) -> Literal["final", "alternate_search", "escalate"]:
    if state.get("verification_passed"):
        return "final"
    if state.get("verification_attempts", 0) <= 1:
        return "alternate_search"
    return "escalate"


def route_after_alternate(state: AgentState) -> Literal["final", "escalate"]:
    if state.get("verification_passed"):
        return "final"
    return "escalate"


# --- Graph Construction --------------------------------------------------------

def build_langgraph_workflow() -> Any:
    """Build and compile the LangGraph workflow."""
    builder = StateGraph(AgentState)

    builder.add_node("guardrail", guardrail_node)
    builder.add_node("clinical", clinical_node)
    builder.add_node("coverage", coverage_node)
    builder.add_node("verification", verification_node)
    builder.add_node("alternate_search", alternate_search_node)
    builder.add_node("final", final_response_node)
    builder.add_node("escalate", escalation_node)

    builder.add_edge(START, "guardrail")
    builder.add_conditional_edges(
        "guardrail",
        route_after_guardrail,
        {"clinical": "clinical", "escalate": "escalate"},
    )
    builder.add_conditional_edges(
        "clinical",
        route_after_clinical,
        {"coverage": "coverage", "escalate": "escalate"},
    )
    builder.add_conditional_edges(
        "coverage",
        route_after_coverage,
        {"verification": "verification", "escalate": "escalate"},
    )
    builder.add_conditional_edges(
        "verification",
        route_after_verification,
        {
            "final": "final",
            "alternate_search": "alternate_search",
            "escalate": "escalate",
        },
    )
    builder.add_conditional_edges(
        "alternate_search",
        route_after_alternate,
        {"final": "final", "escalate": "escalate"},
    )
    builder.add_edge("final", END)
    builder.add_edge("escalate", END)

    return builder.compile()


_COMPILED_GRAPH = None


def get_compiled_graph() -> Any:
    global _COMPILED_GRAPH
    if _COMPILED_GRAPH is None:
        _COMPILED_GRAPH = build_langgraph_workflow()
    return _COMPILED_GRAPH


def run_langgraph_workflow(
    request: PreAuthRequest,
    run_id: str | None = None,
    prompt_version: str = "v1",
) -> PreAuthResponse:
    """Execute decision workflow using compiled LangGraph state machine."""
    run_id = run_id or str(uuid.uuid4())
    start_time = time.time()

    initial_state: AgentState = {
        "request": request,
        "run_id": run_id,
        "correlation_id": run_id,
        "steps": 0,
        "max_steps": MAX_STEPS,
        "total_tool_calls": 0,
        "max_tool_calls": MAX_TOOL_CALLS,
        "tool_calls": [],
        "step_timings": {},
        "trace_events": [],
        "start_time": start_time,
        "deadline_seconds": DEADLINE_SECONDS,
        "prompt_version": prompt_version,
        "token_usage": {},
        "cost_usd": 0.0,
        "verification_passed": False,
        "verification_attempts": 0,
        "verification_issues": [],
        "error": None,
        "fallback_used": False,
        "escalation_required": False,
        "is_unsupported": False,
        "has_pre_existing": False,
        "current_agent": "Workflow Coordinator",
        "current_status": "INITIALIZED",
    }

    workflow_attrs = {
        "preauth.run_id": run_id,
        "preauth.correlation_id": run_id,
        "preauth.agent": "workflow_coordinator",
    }

    with trace_span("preauth.workflow", attributes=workflow_attrs) as span:
        try:
            graph = get_compiled_graph()
            final_state = graph.invoke(initial_state)

            response = _build_response(final_state)
            span.set_attribute("preauth.route", response.route.value if hasattr(response.route, "value") else str(response.route))
            span.set_attribute("preauth.recommendation", response.recommendation.value if hasattr(response.recommendation, "value") else str(response.recommendation))
            span.set_attribute("preauth.verification_passed", response.verification_passed)
            span.set_attribute("preauth.escalation_required", response.escalation_required)
            span.set_attribute("preauth.step_count", final_state.get("steps", 0))
            span.set_attribute("preauth.tool_call_count", len(final_state.get("tool_calls", [])))
            return response
        except Exception as exc:
            record_exception(span, exc)
            initial_state["error"] = str(exc)
            initial_state["reason"] = f"LangGraph runtime error: {exc!s}. Escalating."
            initial_state["escalation_required"] = True
            initial_state["route"] = "medical-review"
            initial_state["recommendation"] = Recommendation.QUERY.value
            _log_trace_event(
                initial_state,
                node="exception_handler",
                agent_name="Workflow Coordinator",
                agent_status="ERROR",
                transition_to="escalate",
                handoff_reason=f"Handled runtime exception: {exc!s}",
                duration=0.0,
            )
            return _build_response(initial_state)

