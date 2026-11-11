"""Verification agent – checks citation grounding and recommendation consistency."""
import time

from .state import AgentState
from .tools import corpus_search


def verify_decision(state: AgentState) -> AgentState:
    """
    Verification node that:
    1. Checks every citation exists in retrieved text
    2. Checks recommendation is supported by binding provisions
    3. Does a second search with a different query if evidence is incomplete
    4. Escalates if verification still fails
    """
    start = time.time()
    state["verification_attempts"] = state.get("verification_attempts", 0) + 1
    issues: list[str] = []

    # Gather retrieved texts
    retrieved_texts: set[str] = set()
    for c in state.get("retrieved_clauses", []):
        if isinstance(c, dict):
            retrieved_texts.add(c.get("text", ""))
        elif hasattr(c, "text"):
            retrieved_texts.add(c.text)
        else:
            retrieved_texts.add(str(c))

    # 1. Check citations are grounded in retrieved text
    for citation in state.get("citations", []):
        if isinstance(citation, dict):
            clause_text = citation.get("clause", "")
        else:
            clause_text = getattr(citation, "clause", "")
        if not clause_text:
            continue
        # Substring match – handles truncated citations vs full stored text
        grounded = any(
            clause_text in rt or rt in clause_text
            for rt in retrieved_texts
        )
        if not grounded:
            issues.append(f"Ungrounded citation: {clause_text[:80]}...")

    # 2. Check recommendation consistency
    rec = state.get("recommendation", "")
    if rec == "APPROVE" and state.get("is_unsupported"):
        issues.append("Cannot approve unsupported clinical category")

    if rec == "APPROVE" and state.get("has_pre_existing"):
        request = state.get("request")
        if request and request.policy_tenure_months < 48:
            issues.append("Cannot approve with pre-existing condition before 48-month waiting period")

    if rec == "APPROVE" and not state.get("citations"):
        issues.append("Cannot approve without supporting citations")

    # 3. If issues found and first attempt, try a second search
    if issues and state["verification_attempts"] <= 1:
        request = state["request"]
        alt_query = f"{request.procedure_name} {request.diagnosis_name} policy eligibility coverage"
        extra = corpus_search(alt_query, top_k=3)
        if extra:
            current = state.get("retrieved_clauses", [])
            state["retrieved_clauses"] = list(current) + extra
        state["verification_passed"] = False
        state["verification_issues"] = issues
        state["steps"] = state.get("steps", 0) + 1
        state["step_timings"]["verification_first"] = round(time.time() - start, 4)
        return state

    # 4. Final verdict
    if issues:
        state["verification_passed"] = False
        state["verification_issues"] = issues
        state["recommendation"] = "QUERY"
        state["reason"] = f"Verification failed: {'; '.join(issues)}. Manual review required."
        state["escalation_required"] = True
        state["route"] = "medical-review"
        state["indicative_limit"] = 0.0
    else:
        state["verification_passed"] = True
        state["verification_issues"] = []

    state["step_timings"]["verification"] = round(time.time() - start, 4)
    state["steps"] = state.get("steps", 0) + 1
    return state

