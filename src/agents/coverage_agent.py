"""Coverage / Decision Agent.

Responsibilities:
- Select and call retrieval tools to fetch binding policy provisions
- Retrieve coverage, exclusions, waiting periods, sub-limits, and day-care lists
- Apply deterministic policy rules
- Formulate a provisional recommendation, reason, indicative limit, and citations

Strict boundaries:
- Must execute retrieval through the centralized tool runner
- Must not bypass the Verification Agent (provisional recommendation only)
"""
from __future__ import annotations

import time
from typing import Any

from data_contracts import Citation, Recommendation

from .clinical_taxonomy import match_waiting_condition
from .state import AgentState, CoverageOutput
from .tools import execute_tool


def _build_citations(clauses: list) -> list[Citation]:
    """Build Citation objects from clause dicts or Chunk objects."""
    citations: list[Citation] = []
    for c in clauses:
        if isinstance(c, dict):
            source = c.get("source", "unknown")
            text = c.get("text", "N/A")
        else:
            source = getattr(c, "source", "unknown")
            text = getattr(c, "text", "N/A")
        citations.append(Citation(source=source, clause=text))
    return citations


class CoverageAgent:
    """Coverage / Decision Agent implementation."""

    name: str = "Coverage / Decision Agent"

    @classmethod
    def evaluate(cls, state: AgentState) -> AgentState:
        """Execute retrieval tools and derive provisional coverage recommendation."""
        start = time.time()
        request = state["request"]
        category = state["clinical_category"]

        # --- Excluded category → immediate escalation ---
        if category == "excluded":
            state.update(
                recommendation=Recommendation.QUERY.value,
                reason="This procedure falls under a permanent exclusion. Coverage is not available.",
                indicative_limit=0.0,
                citations=[],
                escalation_required=True,
                route="medical-review",
            )
            state["current_agent"] = cls.name
            state["current_status"] = "COMPLETED"
            state["steps"] = state.get("steps", 0) + 1
            state.setdefault("step_timings", {})["coverage_verification"] = round(time.time() - start, 4)
            return state

        # --- Tool Call 1: Base coverage retrieval ---
        base_call = execute_tool(
            state,
            "corpus_search",
            f"{request.policy_name} {category} coverage hospitalisation",
            purpose=f"Retrieve base hospitalisation clauses for {category}",
            top_k=5,
        )
        if not base_call["success"]:
            return cls._handle_tool_failure(state, base_call, start)
        base = base_call["results"]

        # --- Tool Call 2: Exclusion / waiting period retrieval ---
        excl_call = execute_tool(
            state,
            "corpus_search",
            f"{category} waiting period exclusion Code-Excl02",
            purpose=f"Retrieve exclusion & waiting period clauses for {category}",
            top_k=5,
        )
        if not excl_call["success"]:
            return cls._handle_tool_failure(state, excl_call, start)
        exclusions = excl_call["results"]

        # --- Tool Call 3: Sub-limit retrieval ---
        sub_call = execute_tool(
            state,
            "corpus_search",
            f"{category} sub-limit room rent cataract per eye",
            purpose=f"Retrieve sub-limit provisions for {category}",
            top_k=3,
        )
        if not sub_call["success"]:
            return cls._handle_tool_failure(state, sub_call, start)
        sublimits = sub_call["results"]
        state["sublimit_clauses"] = sublimits

        # --- Tool Call 4: Daycare procedure check (if applicable) ---
        daycare: list[dict] = []
        if state.get("is_daycare") or request.admission_type.value == "DAYCARE":
            dc_call = execute_tool(
                state,
                "corpus_search",
                f"{request.procedure_name} day-care procedure list",
                purpose=f"Verify {request.procedure_name} against day-care procedure schedule",
                top_k=3,
            )
            if not dc_call["success"]:
                return cls._handle_tool_failure(state, dc_call, start)
            daycare = dc_call["results"]
            state["daycare_clauses"] = daycare

        # --- Tool Call 5: Clause lookup for specific code ---
        lookup_call = execute_tool(
            state,
            "clause_lookup",
            "Code-Excl02",
            purpose="Specific lookup for Code-Excl02 waiting period clause",
        )
        if not lookup_call["success"]:
            return cls._handle_tool_failure(state, lookup_call, start)
        excl02 = lookup_call["results"]

        def _unique(*groups: list) -> list:
            seen_texts: set[str] = set()
            merged: list = []
            for clause in (c for group in groups for c in group):
                text = clause.get("text", "") if isinstance(clause, dict) else getattr(clause, "text", "")
                if text and text not in seen_texts:
                    seen_texts.add(text)
                    merged.append(clause)
            return merged

        # Combine all unique retrieved clauses
        combined = _unique(base, exclusions, sublimits, daycare, excl02)
        # Prioritize exclusionary & specific waiting period clauses for rejection / escalation evidence
        restrictive = _unique(exclusions, excl02, base, sublimits, daycare)

        state["base_clauses"] = base
        state["exclusion_clauses"] = exclusions
        state["retrieved_clauses"] = combined

        # --- No clauses found → escalate ---
        if not combined:
            state.update(
                recommendation=Recommendation.QUERY.value,
                reason="No supporting policy clause was retrieved; manual review is required.",
                indicative_limit=0.0,
                citations=[],
                escalation_required=True,
                route="query-to-hospital",
            )
            state["current_agent"] = cls.name
            state["current_status"] = "COMPLETED"
            state["steps"] = state.get("steps", 0) + 1
            state.setdefault("step_timings", {})["coverage_verification"] = round(time.time() - start, 4)
            return state

        # --- Unsupported clinical category → always escalate ---
        if state.get("is_unsupported"):
            state.update(
                recommendation=Recommendation.QUERY.value,
                reason=f"Unsupported clinical category ({category}). {state.get('escalation_reason', 'Manual review required.')}",
                indicative_limit=0.0,
                escalation_required=True,
                route="medical-review",
            )
            state["citations"] = _build_citations(combined[:3])
            state["current_agent"] = cls.name
            state["current_status"] = "COMPLETED"
            state["steps"] = state.get("steps", 0) + 1
            state.setdefault("step_timings", {})["coverage_verification"] = round(time.time() - start, 4)
            return state

        # --- Pre-existing condition check (48-month waiting period) ---
        if state.get("has_pre_existing") and request.policy_tenure_months < 48:
            state.update(
                recommendation=Recommendation.QUERY.value,
                reason=(
                    f"Pre-existing condition detected. The 48-month waiting period "
                    f"(Code-Excl01) has not been completed (current tenure: "
                    f"{request.policy_tenure_months} months). Escalating to medical review."
                ),
                indicative_limit=0.0,
                escalation_required=True,
                route="medical-review",
            )
            state["citations"] = _build_citations(combined[:3])
            state["current_agent"] = cls.name
            state["current_status"] = "COMPLETED"
            state["steps"] = state.get("steps", 0) + 1
            state.setdefault("step_timings", {})["coverage_verification"] = round(time.time() - start, 4)
            return state

        # --- Specific waiting period rules (Code-Excl02) ---
        indicative_limit = request.estimated_cost
        text_lower = f"{request.procedure_name} {request.diagnosis_name}".lower()

        # Cataract
        cataract_terms = ["cataract", "phacoemulsification", "lens replacement", "iol"]
        if category == "cataract surgery" or match_waiting_condition(text_lower, cataract_terms):
            if request.policy_tenure_months < 24:
                state.update(
                    recommendation=Recommendation.REJECT.value,
                    reason="Cataract surgery is subject to a 24-month Code-Excl02 waiting period.",
                    indicative_limit=0.0,
                )
                state["citations"] = _build_citations(restrictive[:3])
                state["current_agent"] = cls.name
                state["current_status"] = "COMPLETED"
                state["steps"] = state.get("steps", 0) + 1
                state.setdefault("step_timings", {})["coverage_verification"] = round(time.time() - start, 4)
                return state
            indicative_limit = min(request.estimated_cost, 40000.0)

        # Gastrointestinal (Hernia, Fistula, Piles, etc.)
        gastro_waiting = ["hernia", "fistula", "piles", "haemorrhoids", "hemorrhoids"]
        if category == "gastrointestinal treatment" or match_waiting_condition(text_lower, gastro_waiting):
            if match_waiting_condition(text_lower, gastro_waiting) and request.policy_tenure_months < 24:
                state.update(
                    recommendation=Recommendation.REJECT.value,
                    reason=f"{request.procedure_name} is subject to a 24-month Code-Excl02 waiting period.",
                    indicative_limit=0.0,
                )
                state["citations"] = _build_citations(restrictive[:3])
                state["current_agent"] = cls.name
                state["current_status"] = "COMPLETED"
                state["steps"] = state.get("steps", 0) + 1
                state.setdefault("step_timings", {})["coverage_verification"] = round(time.time() - start, 4)
                return state

        # ENT (Tonsillectomy, Sinusitis, etc.)
        ent_waiting = ["tonsillectomy", "sinusitis", "adenoidectomy", "fess", "septoplasty"]
        if category == "ENT treatment" or match_waiting_condition(text_lower, ent_waiting):
            if match_waiting_condition(text_lower, ent_waiting) and request.policy_tenure_months < 24:
                state.update(
                    recommendation=Recommendation.REJECT.value,
                    reason=f"{request.procedure_name} is subject to a 24-month Code-Excl02 waiting period.",
                    indicative_limit=0.0,
                )
                state["citations"] = _build_citations(restrictive[:3])
                state["current_agent"] = cls.name
                state["current_status"] = "COMPLETED"
                state["steps"] = state.get("steps", 0) + 1
                state.setdefault("step_timings", {})["coverage_verification"] = round(time.time() - start, 4)
                return state

        # Renal stone / Lithotripsy / Calculus / Urology Code-Excl02
        renal_waiting = [
            "lithotripsy", "kidney stone", "kidney stones", "ureteric stone",
            "ureteric stones", "urolithiasis", "eswl", "calculus", "calculi",
            "hydrocele", "turp", "prostate",
        ]
        if match_waiting_condition(text_lower, renal_waiting) and request.policy_tenure_months < 24:
            state.update(
                recommendation=Recommendation.REJECT.value,
                reason="Kidney/ureteric stone treatment is subject to a 24-month Code-Excl02 waiting period.",
                indicative_limit=0.0,
            )
            state["citations"] = _build_citations(restrictive[:3])
            state["current_agent"] = cls.name
            state["current_status"] = "COMPLETED"
            state["steps"] = state.get("steps", 0) + 1
            state.setdefault("step_timings", {})["coverage_verification"] = round(time.time() - start, 4)
            return state

        # Orthopedic joint replacement
        ortho_waiting = ["joint replacement", "knee replacement", "hip replacement", "arthroplasty"]
        if category == "orthopedic treatment" or match_waiting_condition(text_lower, ortho_waiting):
            if match_waiting_condition(text_lower, ortho_waiting) and request.policy_tenure_months < 24:
                state.update(
                    recommendation=Recommendation.REJECT.value,
                    reason="Joint replacement surgery is subject to a 24-month Code-Excl02 waiting period.",
                    indicative_limit=0.0,
                )
                state["citations"] = _build_citations(restrictive[:3])
                state["current_agent"] = cls.name
                state["current_status"] = "COMPLETED"
                state["steps"] = state.get("steps", 0) + 1
                state.setdefault("step_timings", {})["coverage_verification"] = round(time.time() - start, 4)
                return state

        # Initial 30-day waiting period
        if request.admission_type.value != "EMERGENCY" and request.policy_tenure_months == 0:
            state.update(
                recommendation=Recommendation.REJECT.value,
                reason="Initial 30-day waiting period has not been completed.",
                indicative_limit=0.0,
            )
            state["citations"] = _build_citations(combined[:3])
            state["current_agent"] = cls.name
            state["current_status"] = "COMPLETED"
            state["steps"] = state.get("steps", 0) + 1
            state.setdefault("step_timings", {})["coverage_verification"] = round(time.time() - start, 4)
            return state

        # Room rent sub-limit notation
        room_category = getattr(request, "room_category", "General")
        sum_insured = getattr(request, "sum_insured", 500000.0)
        reason_extra = ""
        if room_category == "Semi-Private":
            daily_limit = sum_insured * 0.01
            reason_extra = f" Room rent limited to {daily_limit:.0f}/day (1% of sum insured)."
        elif room_category == "Private":
            daily_limit = sum_insured * 0.02
            reason_extra = f" Room rent limited to {daily_limit:.0f}/day (2% of sum insured)."

        # Default Approval
        state.update(
            recommendation=Recommendation.APPROVE.value,
            reason=f"The request meets the retrieved coverage and waiting-period rules.{reason_extra}",
            indicative_limit=indicative_limit,
        )
        state["citations"] = _build_citations(combined[:3])
        state["current_agent"] = cls.name
        state["current_status"] = "COMPLETED"
        state["steps"] = state.get("steps", 0) + 1
        state.setdefault("step_timings", {})["coverage_verification"] = round(time.time() - start, 4)
        return state

    @classmethod
    def _handle_tool_failure(cls, state: AgentState, tool_call: dict, start: float) -> AgentState:
        """Handle tool execution error by escalating safely."""
        state.update(
            recommendation=Recommendation.QUERY.value,
            reason=f"Retrieval tool error ({tool_call['tool']}): {tool_call['error']}. Escalating for manual review.",
            indicative_limit=0.0,
            citations=[],
            escalation_required=True,
            route="medical-review",
            error=tool_call["error"],
        )
        state["current_agent"] = cls.name
        state["current_status"] = "ERROR"
        state["steps"] = state.get("steps", 0) + 1
        state.setdefault("step_timings", {})["coverage_verification"] = round(time.time() - start, 4)
        return state


def verify_coverage(state: AgentState) -> AgentState:
    """Entry point for coverage evaluation node."""
    return CoverageAgent.evaluate(state)
