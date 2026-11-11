"""
Workflow graph implementing the PreAuth decision pipeline.

Uses a state-machine pattern compatible with LangGraph concepts:
nodes (agents), edges (routing), state management, and bounded execution.
"""
import time
import uuid

from data_contracts import (
    Citation,
    PreAuthResponse,
    Recommendation,
    Route,
    recommendation_to_route,
)

from .clinical_agent import classify_clinical_request
from .coverage_agent import verify_coverage
from .state import AgentState
from .verification import verify_decision

MAX_STEPS = 10
MAX_TOOL_CALLS = 20
DEADLINE_SECONDS = 30.0


def _check_bounds(state: AgentState) -> str | None:
    """Check if execution limits are exceeded."""
    if state.get("steps", 0) >= state.get("max_steps", MAX_STEPS):
        return "Maximum steps exceeded"
    if state.get("total_tool_calls", 0) >= state.get("max_tool_calls", MAX_TOOL_CALLS):
        return "Maximum tool calls exceeded"
    elapsed = time.time() - state.get("start_time", time.time())
    if elapsed > state.get("deadline_seconds", DEADLINE_SECONDS):
        return "Deadline exceeded"
    return None


def run_workflow(request, run_id: str | None = None, prompt_version: str = "v1") -> PreAuthResponse:
    """Execute the full preauth workflow graph."""
    run_id = run_id or str(uuid.uuid4())

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
        "start_time": time.time(),
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
    }

    try:
        # Node 1: Input guardrails
        try:
            from src.guardrails.prompt_guard import check_prompt_injection
        except ImportError:
            check_prompt_injection = None

        if check_prompt_injection is not None:
            injection_result = check_prompt_injection(
                request.diagnosis_name,
                request.procedure_name,
                getattr(request, "hospital_name", ""),
                getattr(request, "treating_doctor", ""),
            )
            if injection_result:
                state["recommendation"] = "QUERY"
                state["reason"] = f"Input rejected by safety guardrail: {injection_result}"
                state["escalation_required"] = True
                state["route"] = "medical-review"
                state["indicative_limit"] = 0.0
                state["citations"] = []
                state["step_timings"]["input_guard"] = round(time.time() - state["start_time"], 4)
                return _build_response(state)

        # Node 2: Clinical classification
        bound_err = _check_bounds(state)
        if bound_err:
            return _build_timeout_response(state, bound_err)
        state = classify_clinical_request(state)

        # Node 3: Coverage verification
        bound_err = _check_bounds(state)
        if bound_err:
            return _build_timeout_response(state, bound_err)
        state = verify_coverage(state)

        # Node 4: Verification (first pass)
        bound_err = _check_bounds(state)
        if bound_err:
            return _build_timeout_response(state, bound_err)
        state = verify_decision(state)

        # Node 5: Verification retry if first pass failed
        if not state.get("verification_passed") and state.get("verification_attempts", 0) <= 1:
            bound_err = _check_bounds(state)
            if not bound_err:
                state = verify_decision(state)

        # Node 6: Final grounding check
        try:
            from src.guardrails.prompt_guard import validate_grounding
        except ImportError:
            validate_grounding = None

        if validate_grounding is not None:
            if not validate_grounding(state.get("citations", []), state.get("retrieved_clauses", [])):
                state["recommendation"] = "QUERY"
                state["reason"] = "Citation grounding failed; manual review is required."
                state["indicative_limit"] = 0.0
                state["escalation_required"] = True
                state["verification_passed"] = False

        return _build_response(state)

    except Exception as e:
        state["error"] = str(e)
        state["recommendation"] = "QUERY"
        state["reason"] = f"Workflow error: {e!s}. Escalating for manual review."
        state["escalation_required"] = True
        state["route"] = "medical-review"
        state["indicative_limit"] = 0.0
        state["citations"] = []
        return _build_response(state)


def _build_response(state: AgentState) -> PreAuthResponse:
    """Build final response from agent state."""
    rec_str = state.get("recommendation", "QUERY")
    escalation = state.get("escalation_required", False)

    try:
        rec_enum = Recommendation(rec_str)
    except ValueError:
        rec_enum = Recommendation.QUERY

    route = recommendation_to_route(rec_enum, escalation)

    # Build citations list
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

    # Build retrieved clauses text list
    retrieved = state.get("retrieved_clauses", [])
    retrieved_texts: list[str] = []
    for r in retrieved:
        if isinstance(r, dict):
            retrieved_texts.append(r.get("text", str(r)))
        elif hasattr(r, "text"):
            retrieved_texts.append(r.text)
        else:
            retrieved_texts.append(str(r))

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
            "tool_calls": len(state.get("tool_calls", [])),
            "verification_attempts": state.get("verification_attempts", 0),
            "fallback_used": state.get("fallback_used", False),
            "error": state.get("error"),
        },
    )


def _build_timeout_response(state: AgentState, reason: str) -> PreAuthResponse:
    """Build a timeout / bounds-exceeded response."""
    state["recommendation"] = "QUERY"
    state["reason"] = f"Execution bound reached: {reason}. Escalating."
    state["escalation_required"] = True
    state["route"] = "medical-review"
    state["indicative_limit"] = 0.0
    state["citations"] = []
    return _build_response(state)
