from data_contracts import PreAuthResponse

from .clinical_agent import classify_clinical_request
from .coverage_agent import verify_coverage
from .state import AgentState
from src.guardrails.prompt_guard import validate_grounding


def run_workflow(request) -> PreAuthResponse:
    state: AgentState = {"request": request, "steps": 0}
    state = classify_clinical_request(state)
    state = verify_coverage(state)
    if not validate_grounding(state["citations"], state["retrieved_clauses"]):
        state["recommendation"] = "QUERY"
        state["reason"] = "Citation grounding failed; manual review is required."
        state["indicative_limit"] = 0.0
        state["escalation_required"] = True
    return PreAuthResponse(
        recommendation=state["recommendation"],
        indicative_limit=state["indicative_limit"],
        reason=state["reason"],
        citations=state["citations"],
        escalation_required=state.get("escalation_required", False),
        clinical_category=state["clinical_category"],
        retrieved_clauses=[clause.text for clause in state["retrieved_clauses"]],
        metadata={"steps": state["steps"]},
    )
