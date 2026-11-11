"""Coverage/Decision Agent – retrieves policy clauses and derives recommendation."""
import time

from data_contracts import Citation, Recommendation

from .state import AgentState, ToolCall
from .tools import corpus_search, clause_lookup


def _record_tool_call(state: AgentState, tool: str, query: str, count: int, duration: float) -> None:
    calls = state.get("tool_calls", [])
    calls.append(ToolCall(tool=tool, query=query, result_count=count, duration_seconds=round(duration, 4)))
    state["tool_calls"] = calls
    state["total_tool_calls"] = state.get("total_tool_calls", 0) + 1


def verify_coverage(state: AgentState) -> AgentState:
    """Retrieve policy clauses and determine coverage recommendation."""
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
        state["steps"] = state.get("steps", 0) + 1
        state["step_timings"]["coverage_verification"] = round(time.time() - start, 4)
        return state

    # --- Pass 1: base coverage retrieval ---
    t0 = time.time()
    base = corpus_search(f"{request.policy_name} {category} coverage hospitalisation", top_k=5)
    _record_tool_call(state, "corpus_search", f"base coverage: {category}", len(base), time.time() - t0)

    # --- Pass 2: exclusion / waiting period retrieval ---
    t0 = time.time()
    exclusions = corpus_search(f"{category} waiting period exclusion Code-Excl02", top_k=5)
    _record_tool_call(state, "corpus_search", f"exclusions: {category}", len(exclusions), time.time() - t0)

    # --- Pass 3: sub-limit retrieval ---
    t0 = time.time()
    sublimits = corpus_search(f"{category} sub-limit room rent cataract per eye", top_k=3)
    _record_tool_call(state, "corpus_search", f"sublimits: {category}", len(sublimits), time.time() - t0)
    state["sublimit_clauses"] = sublimits

    # --- Pass 4: daycare check (if applicable) ---
    if state.get("is_daycare") or request.admission_type.value == "DAYCARE":
        t0 = time.time()
        daycare = corpus_search(f"{request.procedure_name} day-care procedure list", top_k=3)
        _record_tool_call(state, "corpus_search", f"daycare: {request.procedure_name}", len(daycare), time.time() - t0)
        state["daycare_clauses"] = daycare

    # --- Pass 5: clause lookup for known codes ---
    t0 = time.time()
    excl02 = clause_lookup("Code-Excl02")
    _record_tool_call(state, "clause_lookup", "Code-Excl02", len(excl02), time.time() - t0)

    # Combine all retrieved clauses
    seen_texts: set[str] = set()
    combined: list[dict] = []
    for clause in base + exclusions + sublimits:
        text = clause.get("text", "") if isinstance(clause, dict) else getattr(clause, "text", "")
        if text and text not in seen_texts:
            seen_texts.add(text)
            combined.append(clause)
    for clause in excl02:
        text = clause.get("text", "") if isinstance(clause, dict) else getattr(clause, "text", "")
        if text and text not in seen_texts:
            seen_texts.add(text)
            combined.append(clause)

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
        state["steps"] = state.get("steps", 0) + 1
        state["step_timings"]["coverage_verification"] = round(time.time() - start, 4)
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
        state["steps"] = state.get("steps", 0) + 1
        state["step_timings"]["coverage_verification"] = round(time.time() - start, 4)
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
        state["steps"] = state.get("steps", 0) + 1
        state["step_timings"]["coverage_verification"] = round(time.time() - start, 4)
        return state

    # --- Category-specific rules ---
    indicative_limit = request.estimated_cost

    # Cataract: 24-month waiting period, sub-limit per eye
    if category == "cataract surgery":
        if request.policy_tenure_months < 24:
            state.update(
                recommendation=Recommendation.REJECT.value,
                reason="Cataract surgery is subject to a 24-month Code-Excl02 waiting period.",
                indicative_limit=0.0,
            )
            state["citations"] = _build_citations(combined[:3])
            state["steps"] = state.get("steps", 0) + 1
            state["step_timings"]["coverage_verification"] = round(time.time() - start, 4)
            return state
        # Apply sub-limit of 40,000 per eye
        indicative_limit = min(request.estimated_cost, 40000.0)

    # Room rent sub-limit check
    room_category = getattr(request, "room_category", "General")
    sum_insured = getattr(request, "sum_insured", 500000.0)
    if room_category == "Semi-Private":
        daily_limit = sum_insured * 0.01
        reason_extra = f" Room rent limited to {daily_limit:.0f}/day (1% of sum insured)."
    elif room_category == "Private":
        daily_limit = sum_insured * 0.02
        reason_extra = f" Room rent limited to {daily_limit:.0f}/day (2% of sum insured)."
    else:
        reason_extra = ""

    # Gastrointestinal conditions with 24-month waiting period
    if category == "gastrointestinal treatment":
        gastro_waiting = {"hernia", "fistula", "piles", "haemorrhoids", "hemorrhoids"}
        procedure_lower = request.procedure_name.lower()
        if any(term in procedure_lower for term in gastro_waiting) and request.policy_tenure_months < 24:
            state.update(
                recommendation=Recommendation.REJECT.value,
                reason=f"{request.procedure_name} is subject to a 24-month Code-Excl02 waiting period.",
                indicative_limit=0.0,
            )
            state["citations"] = _build_citations(combined[:3])
            state["steps"] = state.get("steps", 0) + 1
            state["step_timings"]["coverage_verification"] = round(time.time() - start, 4)
            return state

    # ENT with waiting period
    if category == "ENT treatment":
        ent_waiting = {"tonsillectomy", "sinusitis", "adenoidectomy"}
        procedure_lower = request.procedure_name.lower()
        if any(term in procedure_lower for term in ent_waiting) and request.policy_tenure_months < 24:
            state.update(
                recommendation=Recommendation.REJECT.value,
                reason=f"{request.procedure_name} is subject to a 24-month Code-Excl02 waiting period.",
                indicative_limit=0.0,
            )
            state["citations"] = _build_citations(combined[:3])
            state["steps"] = state.get("steps", 0) + 1
            state["step_timings"]["coverage_verification"] = round(time.time() - start, 4)
            return state

    # Nephrology / renal with Code-Excl02 waiting period for stone disease
    if category == "renal treatment":
        renal_waiting = {"lithotripsy", "kidney stone", "ureteric stone", "urolithiasis", "eswl", "calculus"}
        text_lower = f"{request.procedure_name} {request.diagnosis_name}".lower()
        if any(term in text_lower for term in renal_waiting) and request.policy_tenure_months < 24:
            state.update(
                recommendation=Recommendation.REJECT.value,
                reason="Kidney/ureteric stone treatment is subject to a 24-month Code-Excl02 waiting period.",
                indicative_limit=0.0,
            )
            state["citations"] = _build_citations(combined[:3])
            state["steps"] = state.get("steps", 0) + 1
            state["step_timings"]["coverage_verification"] = round(time.time() - start, 4)
            return state

    # Urology with waiting period
    if category == "urology treatment":
        uro_waiting = {"lithotripsy", "hydrocele", "kidney stone", "ureteric stone", "urolithiasis", "eswl"}
        text_lower = f"{request.procedure_name} {request.diagnosis_name}".lower()
        if any(term in text_lower for term in uro_waiting) and request.policy_tenure_months < 24:
            state.update(
                recommendation=Recommendation.REJECT.value,
                reason=f"Procedure subject to 24-month Code-Excl02 waiting period.",
                indicative_limit=0.0,
            )
            state["citations"] = _build_citations(combined[:3])
            state["steps"] = state.get("steps", 0) + 1
            state["step_timings"]["coverage_verification"] = round(time.time() - start, 4)
            return state

    # Orthopedic joint replacement with waiting period
    if category == "orthopedic treatment":
        ortho_waiting = {"joint replacement", "knee replacement", "hip replacement"}
        text_lower = f"{request.procedure_name} {request.diagnosis_name}".lower()
        if any(term in text_lower for term in ortho_waiting) and request.policy_tenure_months < 24:
            state.update(
                recommendation=Recommendation.REJECT.value,
                reason="Joint replacement surgery is subject to a 24-month Code-Excl02 waiting period.",
                indicative_limit=0.0,
            )
            state["citations"] = _build_citations(combined[:3])
            state["steps"] = state.get("steps", 0) + 1
            state["step_timings"]["coverage_verification"] = round(time.time() - start, 4)
            return state

    # Initial 30-day waiting period (except emergency and accidental)
    if request.admission_type.value != "EMERGENCY" and request.policy_tenure_months == 0:
        state.update(
            recommendation=Recommendation.REJECT.value,
            reason="Initial 30-day waiting period has not been completed.",
            indicative_limit=0.0,
        )
        state["citations"] = _build_citations(combined[:3])
        state["steps"] = state.get("steps", 0) + 1
        state["step_timings"]["coverage_verification"] = round(time.time() - start, 4)
        return state

    # --- Default: Approve ---
    state.update(
        recommendation=Recommendation.APPROVE.value,
        reason=f"The request meets the retrieved coverage and waiting-period rules.{reason_extra}",
        indicative_limit=indicative_limit,
    )
    state["citations"] = _build_citations(combined[:3])
    state["steps"] = state.get("steps", 0) + 1
    state["step_timings"]["coverage_verification"] = round(time.time() - start, 4)
    return state


def _build_citations(clauses: list) -> list[Citation]:
    """Build Citation objects from clause dicts or Chunk objects."""
    citations = []
    for c in clauses:
        if isinstance(c, dict):
            source = c.get("source", "unknown")
            text = c.get("text", "N/A")
        else:
            source = getattr(c, "source", "unknown")
            text = getattr(c, "text", "N/A")
        # Use full text so grounding check can match
        citations.append(Citation(source=source, clause=text))
    return citations
