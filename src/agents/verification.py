"""Verification Agent.

Responsibilities:
- Validate that every cited clause is grounded in retrieved text
- Verify recommendation consistency with binding policy provisions
- Trigger an alternate retrieval tool call if initial evidence is incomplete
- Escalate to medical review if verification fails after retry
- Enforce that no unsupported, ungrounded, or conflicting decision is approved
"""
from __future__ import annotations

import time
from typing import Any

from data_contracts import Citation, Recommendation

from .state import AgentState, VerificationOutput
from .tools import execute_tool


class VerificationAgent:
    """Dedicated Verification Agent implementation."""

    name: str = "Verification Agent"

    @classmethod
    def verify(cls, state: AgentState) -> AgentState:
        """Execute verification of citations, policy grounding, and consistency."""
        start = time.time()
        state["verification_attempts"] = state.get("verification_attempts", 0) + 1
        attempt = state["verification_attempts"]
        issues: list[str] = []

        # 1. Gather retrieved texts for grounding comparison
        retrieved_texts: set[str] = set()
        for c in state.get("retrieved_clauses", []):
            if isinstance(c, dict):
                retrieved_texts.add(c.get("text", ""))
            elif hasattr(c, "text"):
                retrieved_texts.add(c.text)
            else:
                retrieved_texts.add(str(c))

        # 2. Check citation grounding
        citations = state.get("citations", [])
        for citation in citations:
            if isinstance(citation, dict):
                clause_text = citation.get("clause", "")
            else:
                clause_text = getattr(citation, "clause", "")
            if not clause_text:
                continue
            grounded = any(
                clause_text in rt or rt in clause_text
                for rt in retrieved_texts
            )
            if not grounded:
                issues.append(f"Ungrounded citation: {clause_text[:80]}...")

        # 3. Check decision consistency
        rec = state.get("recommendation", "")
        if rec == "APPROVE":
            if state.get("is_unsupported"):
                issues.append("Cannot approve unsupported clinical category")

            if state.get("has_pre_existing"):
                req = state.get("request")
                if req and req.policy_tenure_months < 48:
                    issues.append("Cannot approve with pre-existing condition before 48-month waiting period")

            if not citations:
                issues.append("Cannot approve without supporting citations")

        # 4. If issues found on first attempt, execute alternate retrieval tool call
        if issues and attempt == 1:
            req = state.get("request")
            if req:
                alt_query = f"{req.procedure_name} {req.diagnosis_name} policy eligibility coverage"
                alt_call = execute_tool(
                    state,
                    "corpus_search",
                    alt_query,
                    purpose="Alternate verification search to ground citations and resolve evidence gaps",
                    retry_number=1,
                    top_k=3,
                )
                if alt_call["success"] and alt_call["results"]:
                    current = state.get("retrieved_clauses", [])
                    state["retrieved_clauses"] = list(current) + alt_call["results"]

            state["verification_passed"] = False
            state["verification_issues"] = issues
            state["current_agent"] = cls.name
            state["current_status"] = "RETRYING"
            state["steps"] = state.get("steps", 0) + 1
            state.setdefault("step_timings", {})["verification_first"] = round(time.time() - start, 4)
            return state

        # 5. Final verification verdict
        if issues:
            state["verification_passed"] = False
            state["verification_issues"] = issues
            state["recommendation"] = Recommendation.QUERY.value
            state["reason"] = f"Verification failed: {'; '.join(issues)}. Manual review required."
            state["escalation_required"] = True
            state["route"] = "medical-review"
            state["indicative_limit"] = 0.0
            state["current_status"] = "ESCALATED"
        else:
            state["verification_passed"] = True
            state["verification_issues"] = []
            state["current_status"] = "PASSED"

        state["current_agent"] = cls.name
        state["steps"] = state.get("steps", 0) + 1
        state.setdefault("step_timings", {})["verification"] = round(time.time() - start, 4)
        return state


def verify_decision(state: AgentState) -> AgentState:
    """Entry point for verification node."""
    return VerificationAgent.verify(state)
