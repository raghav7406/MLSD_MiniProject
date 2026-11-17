"""
Clinical / Intake Agent.

Responsibilities:
- Classify diagnosis and procedure into verified clinical categories using semantic taxonomy
- Tolerates spelling errors, medical synonyms, and clinical abbreviations
- Identify admission classification (PLANNED, EMERGENCY, DAYCARE)
- Flag risk indicators: daycare procedure, pre-existing conditions, permanent exclusions
- Enforces fail-safe escalation for unclassified or ambiguous conditions (zero silent auto-approvals)

Strict boundaries:
- Must not evaluate policy coverage or waiting periods
- Must not make approval or financial decisions
"""
from __future__ import annotations

import time
from typing import Any

from .clinical_taxonomy import (
    ClinicalTaxonomyClassifier,
    check_is_daycare,
    check_is_excluded,
)
from .state import AgentState, ClinicalOutput


class ClinicalAgent:
    """Clinical / Intake Agent implementation with semantic taxonomy classification."""

    name: str = "Clinical / Intake Agent"

    @classmethod
    def process(cls, state: AgentState) -> ClinicalOutput:
        """Analyze request entities and derive clinical classification using semantic embeddings and fuzzy metrics."""
        start = time.time()
        request = state["request"]
        text = f"{request.diagnosis_name} {request.procedure_name}".strip()

        # 1. Semantic & fuzzy check for permanent exclusions
        if check_is_excluded(text):
            duration = round(time.time() - start, 4)
            return ClinicalOutput(
                clinical_category="excluded",
                admission_classification=request.admission_type.value,
                is_daycare=False,
                has_pre_existing=bool(getattr(request, "pre_existing_conditions", [])),
                is_unsupported=True,
                escalation_reason="Procedure matches a permanent exclusion category.",
                duration_seconds=duration,
            )

        # 2. Semantic vector taxonomy classification (character n-grams handles typos & stems)
        classifier = ClinicalTaxonomyClassifier.get_instance()
        category, confidence = classifier.classify(text)

        # 3. Fail-safe boundary: if confidence is below minimum threshold, escalate for medical review
        is_unsupported = False
        escalation_reason = ""

        if confidence < 0.05:
            is_unsupported = True
            category = "unclassified"
            escalation_reason = f"Clinical terminology unclassified or unrecognized (confidence: {confidence:.3f})."

        # 4. Check daycare eligibility via semantic and fuzzy matching against schedule
        is_daycare = check_is_daycare(text)

        # Flag admission type discrepancy
        if request.admission_type.value == "DAYCARE" and not is_daycare:
            is_unsupported = True
            escalation_reason = "Procedure not recognized as a standard day-care procedure."

        has_pre_existing = bool(getattr(request, "pre_existing_conditions", []))
        duration = round(time.time() - start, 4)

        return ClinicalOutput(
            clinical_category=category,
            admission_classification=request.admission_type.value,
            is_daycare=is_daycare,
            has_pre_existing=has_pre_existing,
            is_unsupported=is_unsupported,
            escalation_reason=escalation_reason,
            duration_seconds=duration,
        )


def classify_clinical_request(state: AgentState) -> AgentState:
    """Entry point for clinical intake classification node."""
    output = ClinicalAgent.process(state)

    state["clinical_category"] = output.clinical_category
    state["admission_classification"] = output.admission_classification
    state["is_daycare"] = output.is_daycare
    state["has_pre_existing"] = output.has_pre_existing
    state["is_unsupported"] = output.is_unsupported
    if output.escalation_reason:
        state["escalation_reason"] = output.escalation_reason
        state["escalation_required"] = True

    state["current_agent"] = ClinicalAgent.name
    state["current_status"] = "COMPLETED"
    state["steps"] = state.get("steps", 0) + 1

    timings = state.setdefault("step_timings", {})
    timings["clinical_classification"] = output.duration_seconds

    return state
