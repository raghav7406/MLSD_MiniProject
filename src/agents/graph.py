"""
Workflow graph implementing the PreAuth multi-agent decision pipeline.

Architecture:
- Node 1: Input Guardrails Node
- Node 2: Clinical / Intake Agent
- Node 3: Coverage / Decision Agent (centralized tool execution)
- Node 4: Verification Agent (citation grounding & consistency)
- Node 5: Verification Retry (alternate retrieval & re-verification)

Enforces:
- Named explicit transition functions
- Trace event and hand-off logging
- Hard execution bounds (max steps, max tool calls, wall-clock deadline)
- Safe fallback / escalation on all failure modes
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Literal

from data_contracts import (
    Citation,
    PreAuthRequest,
    PreAuthResponse,
    Recommendation,
    Route,
    recommendation_to_route,
)

from .clinical_agent import ClinicalAgent, classify_clinical_request
from .coverage_agent import CoverageAgent, verify_coverage
from .state import AgentState, TraceEvent
from .verification import VerificationAgent, verify_decision

MAX_STEPS = 10
MAX_TOOL_CALLS = 20
DEADLINE_SECONDS = 30.0


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


# --- Named Routing Functions ---------------------------------------------------

def route_after_guardrail(state: AgentState) -> Literal["clinical", "escalate_guardrail"]:
    """Determine transition after input guardrail check."""
    if state.get("error") and "guardrail" in state.get("error", "").lower():
        return "escalate_guardrail"
    if state.get("escalation_required") and "guardrail" in state.get("reason", "").lower():
        return "escalate_guardrail"
    return "clinical"


def route_after_clinical(state: AgentState) -> Literal["coverage", "escalate_clinical"]:
    """Determine transition after Clinical / Intake classification."""
    if state.get("clinical_category") == "excluded":
        return "coverage"  # Coverage agent handles exclusion provisions cleanly
    if state.get("error"):
        return "escalate_clinical"
    return "coverage"


def route_after_coverage(state: AgentState) -> Literal["verification", "escalate_coverage"]:
    """Determine transition after Coverage / Decision evaluation."""
    if state.get("error"):
        return "escalate_coverage"
    return "verification"


def route_after_verification(state: AgentState) -> Literal["final_response", "alternate_search", "escalate_verification"]:
    """Determine transition after Verification Agent check."""
    if state.get("verification_passed"):
        return "final_response"
    # If first verification attempt failed, trigger alternate search retry
    if state.get("verification_attempts", 0) <= 1:
        return "alternate_search"
    return "escalate_verification"


# --- Workflow Runner -----------------------------------------------------------

def run_workflow(request: PreAuthRequest, run_id: str | None = None, prompt_version: str = "v1") -> PreAuthResponse:
    """Execute the multi-agent decision workflow graph."""
    run_id = run_id or str(uuid.uuid4())
    start_time = time.time()

    state: AgentState = {
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

    try:
        # =====================================================================
        # Node 1: Input Guardrail Check
        # =====================================================================
        node_start = time.time()
        try:
            from src.guardrails.prompt_guard import check_prompt_injection, check_toxicity
        except ImportError:
            check_prompt_injection = None
            check_toxicity = None

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

        if guardrail_err:
            state["recommendation"] = Recommendation.QUERY.value
            state["reason"] = f"Input rejected by safety guardrail: {guardrail_err}"
            state["escalation_required"] = True
            state["route"] = "medical-review"
            state["indicative_limit"] = 0.0
            state["citations"] = []
            state["verification_passed"] = False
            _log_trace_event(
                state,
                node="input_guardrails",
                agent_name="Guardrail Node",
                agent_status="REJECTED",
                transition_to="escalation",
                handoff_reason=f"Adversarial or toxic content flagged: {guardrail_err}",
                duration=guard_duration,
            )
            return _build_response(state)

        next_route = route_after_guardrail(state)
        _log_trace_event(
            state,
            node="input_guardrails",
            agent_name="Guardrail Node",
            agent_status="PASSED",
            transition_to=next_route,
            handoff_reason="Request text passed input safety and injection filters.",
            duration=guard_duration,
        )

        # =====================================================================
        # Node 2: Clinical / Intake Agent
        # =====================================================================
        bound_err = _check_bounds(state)
        if bound_err:
            return _build_timeout_response(state, bound_err)

        node_start = time.time()
        state = classify_clinical_request(state)
        clin_duration = time.time() - node_start
        next_route = route_after_clinical(state)

        _log_trace_event(
            state,
            node="clinical_intake",
            agent_name=ClinicalAgent.name,
            agent_status=state.get("current_status", "COMPLETED"),
            transition_to=next_route,
            handoff_reason=(
                f"Classified as '{state.get('clinical_category')}', "
                f"daycare={state.get('is_daycare')}, PED={state.get('has_pre_existing')}. "
                f"Handoff to Coverage Agent."
            ),
            duration=clin_duration,
        )

        # =====================================================================
        # Node 3: Coverage / Decision Agent
        # =====================================================================
        bound_err = _check_bounds(state)
        if bound_err:
            return _build_timeout_response(state, bound_err)

        node_start = time.time()
        state = verify_coverage(state)
        cov_duration = time.time() - node_start
        next_route = route_after_coverage(state)

        _log_trace_event(
            state,
            node="coverage_decision",
            agent_name=CoverageAgent.name,
            agent_status=state.get("current_status", "COMPLETED"),
            transition_to=next_route,
            handoff_reason=(
                f"Provisional decision: {state.get('recommendation')} with "
                f"{len(state.get('citations', []))} citations. Handoff to Verification Agent."
            ),
            duration=cov_duration,
        )

        # =====================================================================
        # Node 4: Verification Agent (Pass 1)
        # =====================================================================
        bound_err = _check_bounds(state)
        if bound_err:
            return _build_timeout_response(state, bound_err)

        node_start = time.time()
        state = verify_decision(state)
        ver_duration = time.time() - node_start
        next_route = route_after_verification(state)

        # =====================================================================
        # Node 5: Verification Retry (Alternate Search if needed)
        # =====================================================================
        if next_route == "alternate_search":
            _log_trace_event(
                state,
                node="verification_attempt_1",
                agent_name=VerificationAgent.name,
                agent_status="RETRY_REQUESTED",
                transition_to="alternate_search",
                handoff_reason=f"Evidence incomplete: {'; '.join(state.get('verification_issues', []))}. Triggering alternate search.",
                duration=ver_duration,
            )

            bound_err = _check_bounds(state)
            if bound_err:
                return _build_timeout_response(state, bound_err)

            node_start = time.time()
            state = verify_decision(state)
            ver_duration2 = time.time() - node_start
            next_route = route_after_verification(state)

            _log_trace_event(
                state,
                node="verification_attempt_2",
                agent_name=VerificationAgent.name,
                agent_status="COMPLETED" if state.get("verification_passed") else "ESCALATED",
                transition_to=next_route,
                handoff_reason=(
                    "Verification passed after alternate retrieval."
                    if state.get("verification_passed")
                    else f"Verification failed after retry: {'; '.join(state.get('verification_issues', []))}. Escalated."
                ),
                duration=ver_duration2,
            )
        else:
            _log_trace_event(
                state,
                node="verification_attempt_1",
                agent_name=VerificationAgent.name,
                agent_status="COMPLETED" if state.get("verification_passed") else "ESCALATED",
                transition_to=next_route,
                handoff_reason=(
                    "All citations grounded and provisions verified."
                    if state.get("verification_passed")
                    else f"Verification issues: {'; '.join(state.get('verification_issues', []))}. Escalated."
                ),
                duration=ver_duration,
            )

        # =====================================================================
        # Node 6: Final Grounding Guardrail Check
        # =====================================================================
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

        return _build_response(state)

    except Exception as e:
        state["error"] = str(e)
        state["recommendation"] = Recommendation.QUERY.value
        state["reason"] = f"Workflow error: {e!s}. Escalating for manual review."
        state["escalation_required"] = True
        state["route"] = "medical-review"
        state["indicative_limit"] = 0.0
        state["citations"] = []
        state["verification_passed"] = False
        _log_trace_event(
            state,
            node="exception_handler",
            agent_name="Workflow Coordinator",
            agent_status="ERROR",
            transition_to="escalate",
            handoff_reason=f"Handled unhandled exception safely: {e!s}",
            duration=0.0,
        )
        return _build_response(state)


def _build_response(state: AgentState) -> PreAuthResponse:
    """Construct stable public PreAuthResponse from final internal state."""
    rec_str = state.get("recommendation", "QUERY")
    escalation = state.get("escalation_required", False)

    try:
        rec_enum = Recommendation(rec_str)
    except ValueError:
        rec_enum = Recommendation.QUERY

    # Determine public routing outcome
    route = recommendation_to_route(rec_enum, escalation)

    # Format citations
    raw_citations = state.get("citations", [])
    citations: list[Citation] = []
    for c in raw_citations:
        if isinstance(c, Citation):
            citations.append(c)
        elif isinstance(c, dict):
            citations.append(
                Citation(
                    source=c.get("source", "unknown"),
                    clause=c.get("clause", c.get("text", "N/A")),
                )
            )
        elif hasattr(c, "source") and hasattr(c, "clause"):
            citations.append(c)

    # Format retrieved clauses
    retrieved = state.get("retrieved_clauses", [])
    retrieved_texts: list[str] = []
    for r in retrieved:
        if isinstance(r, dict):
            retrieved_texts.append(r.get("text", str(r)))
        elif hasattr(r, "text"):
            retrieved_texts.append(r.text)
        else:
            retrieved_texts.append(str(r))

    trace_events = state.get("trace_events", [])
    tool_calls = state.get("tool_calls", [])

    return PreAuthResponse(
        run_id=state.get("run_id", ""),
        recommendation=rec_enum,
        route=route,
        indicative_limit=state.get("indicative_limit", 0.0),
        reason=state.get("reason", "No recommendation could be made."),
        citations=citations,
        escalation_required=escalation,
        clinical_category=state.get("clinical_category"),
        retrieved_clauses=retrieved_texts,
        verification_passed=state.get("verification_passed", False),
        prompt_version=state.get("prompt_version", "v1"),
        token_usage=state.get("token_usage", {}),
        cost_usd=state.get("cost_usd", 0.0),
        step_timings=state.get("step_timings", {}),
        metadata={
            "steps": state.get("steps", 0),
            "tool_calls_count": len(tool_calls),
            "tool_calls": tool_calls,
            "verification_attempts": state.get("verification_attempts", 0),
            "trace_events": trace_events,
            "handoff_log": trace_events,
            "fallback_used": state.get("fallback_used", False),
            "error": state.get("error"),
        },
    )


def _build_timeout_response(state: AgentState, reason: str) -> PreAuthResponse:
    """Build bounded timeout / bound-breached response safely."""
    state["recommendation"] = Recommendation.QUERY.value
    state["reason"] = f"Execution bound reached: {reason}. Escalating."
    state["escalation_required"] = True
    state["route"] = "medical-review"
    state["indicative_limit"] = 0.0
    state["citations"] = []
    state["verification_passed"] = False
    _log_trace_event(
        state,
        node="bound_checker",
        agent_name="Workflow Coordinator",
        agent_status="BOUND_BREACHED",
        transition_to="escalate",
        handoff_reason=reason,
        duration=0.0,
    )
    return _build_response(state)
