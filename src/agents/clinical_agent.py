"""Clinical / Intake Agent.

Responsibilities:
- Classify diagnosis and procedure into clinical categories
- Identify admission classification (PLANNED, EMERGENCY, DAYCARE)
- Flag risk indicators: daycare procedure, pre-existing conditions, permanent exclusions
- Flag unsupported clinical terminology

Strict boundaries:
- Must not evaluate policy coverage or waiting periods
- Must not make approval or financial decisions
"""
from __future__ import annotations

import time
from typing import Any

from .state import AgentState, ClinicalOutput

# --- Clinical category mappings -----------------------------------------------

_OPHTHALMOLOGY_TERMS = {
    "cataract", "phacoemulsification", "lens replacement", "iol",
    "glaucoma", "pterygium", "chalazion", "vitrectomy",
}
_CARDIOLOGY_TERMS = {
    "cardiac", "angioplasty", "bypass", "cabg", "coronary",
    "valve replacement", "pacemaker", "stent", "angiography",
}
_ORTHOPEDICS_TERMS = {
    "joint replacement", "hip replacement", "knee replacement",
    "fracture", "arthroscopy", "spine", "disc",
}
_ONCOLOGY_TERMS = {
    "chemotherapy", "radiotherapy", "cancer", "tumour", "tumor",
    "oncology", "biopsy malignant",
}
_NEPHROLOGY_TERMS = {
    "dialysis", "renal", "kidney", "nephrectomy",
}
_ENT_TERMS = {
    "tonsillectomy", "adenoidectomy", "sinusitis", "fess", "septoplasty",
    "tympanoplasty", "myringotomy", "nasal polypectomy",
}
_GASTRO_TERMS = {
    "hernia", "fistula", "piles", "haemorrhoids", "hemorrhoids",
    "cholecystectomy", "appendectomy", "colonoscopy", "endoscopy",
}
_UROLOGY_TERMS = {
    "lithotripsy", "hydrocele", "turp", "prostate", "cystoscopy",
    "urolithiasis", "kidney stone", "ureteric stone",
}
_GYNECOLOGY_TERMS = {
    "hysteroscopy", "d&c", "dilation and curettage",
    "fibromyoma", "dysfunctional uterine bleeding",
}
_DENTAL_TERMS = {
    "dental surgery", "dental accident",
}

_CATEGORY_MAP = [
    ("cataract surgery", _OPHTHALMOLOGY_TERMS),
    ("cardiac treatment", _CARDIOLOGY_TERMS),
    ("orthopedic treatment", _ORTHOPEDICS_TERMS),
    ("oncology treatment", _ONCOLOGY_TERMS),
    ("renal treatment", _NEPHROLOGY_TERMS),
    ("ENT treatment", _ENT_TERMS),
    ("gastrointestinal treatment", _GASTRO_TERMS),
    ("urology treatment", _UROLOGY_TERMS),
    ("gynecology treatment", _GYNECOLOGY_TERMS),
    ("dental treatment", _DENTAL_TERMS),
]

DAYCARE_PROCEDURES = {
    "cataract", "phacoemulsification", "lens replacement", "dialysis",
    "chemotherapy", "radiotherapy", "lithotripsy", "tonsillectomy",
    "adenoidectomy", "sinusitis", "fess", "angiography", "angioplasty",
    "hysteroscopy", "d&c", "fracture", "plastering", "hydrocele",
    "arthroscopy", "colonoscopy", "endoscopy", "cholecystectomy",
    "appendectomy", "hernia", "piles", "fistula", "varicocele",
    "circumcision", "skin lesion", "breast lump", "ganglion",
    "carpal tunnel", "trigger finger", "tympanoplasty", "myringotomy",
    "nasal polypectomy", "septoplasty", "pterygium", "chalazion",
    "abscess", "urethral", "cystoscopy", "turp",
}

_EXCLUDED_TERMS = {
    "cosmetic", "aesthetic", "liposuction", "bariatric", "obesity surgery",
    "gender change", "ivf", "infertility", "surrogacy", "experimental",
    "self-inflicted", "substance abuse", "alcohol", "vitamin", "supplement",
    "spectacles", "contact lens", "eyesight correction",
}


class ClinicalAgent:
    """Clinical / Intake Agent implementation."""

    name: str = "Clinical / Intake Agent"

    @classmethod
    def process(cls, state: AgentState) -> ClinicalOutput:
        """Analyze request entities and derive clinical classification."""
        start = time.time()
        request = state["request"]
        text = f"{request.diagnosis_name} {request.procedure_name}".lower()

        # Check permanent exclusions
        if any(term in text for term in _EXCLUDED_TERMS):
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

        # Match clinical category
        category = "general hospitalisation"
        for cat_name, terms in _CATEGORY_MAP:
            if any(term in text for term in terms):
                category = cat_name
                break

        is_daycare = any(term in text for term in DAYCARE_PROCEDURES)
        is_unsupported = False
        escalation_reason = ""

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
