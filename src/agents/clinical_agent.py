from .state import AgentState


def classify_clinical_request(state: AgentState) -> AgentState:
    request = state["request"]
    text = f"{request.diagnosis_name} {request.procedure_name}".lower()
    if any(term in text for term in ("cataract", "phacoemulsification", "lens replacement")):
        category = "cataract surgery"
    elif any(term in text for term in ("dialysis", "renal")):
        category = "renal treatment"
    elif any(term in text for term in ("cardiac", "angioplasty", "bypass")):
        category = "cardiac treatment"
    else:
        category = "general hospitalisation"
    state["clinical_category"] = category
    return state
