from data_contracts import Citation, Recommendation

from .state import AgentState
from .tools import retrieve_corpus_clause


def verify_coverage(state: AgentState) -> AgentState:
    request = state["request"]
    category = state["clinical_category"]
    base = retrieve_corpus_clause(f"{request.policy_name} {category} coverage hospitalisation")
    exclusions = retrieve_corpus_clause(f"{category} waiting period exclusion Code-Excl02")
    clauses = base + [clause for clause in exclusions if clause not in base]
    state["base_clauses"] = base
    state["exclusion_clauses"] = exclusions
    state["retrieved_clauses"] = clauses
    state["steps"] = state.get("steps", 0) + 1
    if not clauses:
        state.update(
            recommendation=Recommendation.QUERY.value,
            reason="No supporting policy clause was retrieved; manual review is required.",
            indicative_limit=0.0,
            citations=[],
            escalation_required=True,
        )
        return state
    if category == "cataract surgery" and request.policy_tenure_months < 24:
        state.update(
            recommendation=Recommendation.REJECT.value,
            reason="Cataract surgery is subject to a 24-month Code-Excl02 waiting period.",
            indicative_limit=0.0,
        )
    else:
        state.update(
            recommendation=Recommendation.APPROVE.value,
            reason="The request meets the retrieved coverage and waiting-period rules.",
            indicative_limit=request.estimated_cost,
        )
    state["citations"] = [Citation(source=c.source, clause=c.text) for c in clauses[:3]]
    return state
