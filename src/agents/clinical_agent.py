"""Clinical/Intake Agent – classifies the clinical category and flags edge cases."""
import time

from .state import AgentState

# --- Clinical category mappings -----------------------------------------------

_OPHTHALMOLOGY_TERMS = {"cataract", "phacoemulsification", "lens replacement", "iol",
                        "glaucoma", "pterygium", "chalazion", "vitrectomy"}
_CARDIOLOGY_TERMS = {"cardiac", "angioplasty", "bypass", "cabg", "coronary",
                     "valve replacement", "pacemaker", "stent", "angiography"}
_ORTHOPEDICS_TERMS = {"joint replacement", "hip replacement", "knee replacement",
                      "fracture", "arthroscopy", "spine", "disc"}
_ONCOLOGY_TERMS = {"chemotherapy", "radiotherapy", "cancer", "tumour", "tumor",
                   "oncology", "biopsy malignant"}
_NEPHROLOGY_TERMS = {"dialysis", "renal", "kidney", "nephrectomy"}
_ENT_TERMS = {"tonsillectomy", "adenoidectomy", "sinusitis", "fess", "septoplasty",
              "tympanoplasty", "myringotomy", "nasal polypectomy"}
_GASTRO_TERMS = {"hernia", "fistula", "piles", "haemorrhoids", "hemorrhoids",
                 "cholecystectomy", "appendectomy", "colonoscopy", "endoscopy"}
_UROLOGY_TERMS = {"lithotripsy", "hydrocele", "turp", "prostate", "cystoscopy",
                  "urolithiasis", "kidney stone", "ureteric stone"}
_GYNECOLOGY_TERMS = {"hysteroscopy", "d&c", "dilation and curettage",
                     "fibromyoma", "dysfunctional uterine bleeding"}
_DENTAL_TERMS = {"dental surgery", "dental accident"}

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

# --- Daycare procedure keywords -----------------------------------------------

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

# Permanently excluded categories
_EXCLUDED_TERMS = {
    "cosmetic", "aesthetic", "liposuction", "bariatric", "obesity surgery",
    "gender change", "ivf", "infertility", "surrogacy", "experimental",
    "self-inflicted", "substance abuse", "alcohol", "vitamin", "supplement",
    "spectacles", "contact lens", "eyesight correction",
}


def classify_clinical_request(state: AgentState) -> AgentState:
    """Classify the clinical request and flag special cases."""
    start = time.time()
    request = state["request"]
    text = f"{request.diagnosis_name} {request.procedure_name}".lower()

    # Check permanent exclusions first
    if any(term in text for term in _EXCLUDED_TERMS):
        state["clinical_category"] = "excluded"
        state["is_unsupported"] = True
        state["escalation_required"] = True
        state["escalation_reason"] = "Procedure matches a permanent exclusion category."
        state["steps"] = state.get("steps", 0) + 1
        state["step_timings"]["clinical_classification"] = round(time.time() - start, 4)
        return state

    # Classify into known categories
    category = "general hospitalisation"
    for cat_name, terms in _CATEGORY_MAP:
        if any(term in text for term in terms):
            category = cat_name
            break

    state["clinical_category"] = category

    # Flag if it's a daycare procedure
    state["is_daycare"] = any(term in text for term in DAYCARE_PROCEDURES)

    # If admission type is DAYCARE but procedure isn't recognized daycare
    if request.admission_type.value == "DAYCARE" and not state["is_daycare"]:
        state["is_unsupported"] = True
        state["escalation_reason"] = "Procedure not recognized as a standard day-care procedure."

    # Flag unknown / unsupported categories
    if category == "general hospitalisation":
        state["is_unsupported"] = state.get("is_unsupported", False)
        # Not necessarily unsupported, just general

    # Flag pre-existing conditions
    pre_existing = getattr(request, "pre_existing_conditions", [])
    if pre_existing:
        state["has_pre_existing"] = True
    else:
        state["has_pre_existing"] = False

    state["steps"] = state.get("steps", 0) + 1
    state["step_timings"]["clinical_classification"] = round(time.time() - start, 4)
    return state
