"""
Clinical Taxonomy Semantic Classifier.

Replaces naive keyword matching with a semantic & typo-tolerant taxonomy classifier:
- Uses word TF-IDF vectorization and cosine similarity over clinical category profiles.
- Distinguishes unigrams from compound multi-word terms (e.g., 'contact lens' vs 'lens replacement').
- Uses strict length-bounded sequence matching to resolve spelling mistakes (e.g. 'kidneyy',
  'catract', 'phacoemulsifcation', 'appendicittis') without false positive word-stem collisions.
- Strictly validates clinical anchor terms before assigning a category.
- Enforces fail-safe escalation for unrecognized or ambiguous conditions (never silently auto-approving).
"""
from __future__ import annotations

import difflib
from typing import Sequence

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

TAXONOMY_PROFILES: dict[str, str] = {
    "cataract surgery": (
        "cataract senile immature mature cataract phacoemulsification lens replacement "
        "intraocular lens iol eye vision posterior chamber opacification capsulotomy "
        "anterior segment ophthalmic ophthalmology"
    ),
    "cardiac treatment": (
        "cardiac coronary artery bypass cabg angioplasty stent pacemaker valve replacement "
        "heart myocardial infarction ischemia catheterization ptca angiography cardiology"
    ),
    "orthopedic treatment": (
        "joint replacement hip replacement knee replacement total knee total hip fracture "
        "arthroscopy spine disc prolapse spondylosis microdiscectomy laminectomy bone "
        "ligament tear meniscus tendon orthopedic orthopaedics"
    ),
    "oncology treatment": (
        "cancer tumor tumour chemotherapy radiotherapy oncology malignant neoplasm "
        "carcinoma biopsy excision radiation infusion sarcoma leukemia lymphoma"
    ),
    "renal treatment": (
        "dialysis hemodialysis peritoneal dialysis renal failure nephrectomy transplant "
        "ckd chronic kidney disease end stage renal nephrology"
    ),
    "urology treatment": (
        "lithotripsy kidney stone renal calculus ureteric stone hydrocele turp transurethral "
        "prostate cystoscopy urolithiasis eswl bladder urinary nephrolithiasis kidney calculi"
    ),
    "ENT treatment": (
        "tonsillectomy adenoidectomy sinusitis fess functional endoscopic sinus surgery "
        "septoplasty deviated septum tympanoplasty eardrum myringotomy nasal polypectomy "
        "otolaryngology ear nose throat"
    ),
    "gastrointestinal treatment": (
        "hernia inguinal umbilical hernia repair hernioplasty piles haemorrhoids hemorrhoids "
        "fistula cholecystectomy gallbladder stones appendicitis appendectomy colonoscopy endoscopy gastro"
    ),
    "gynecology treatment": (
        "hysteroscopy dilation and curettage d&c fibroma fibromyoma uterine bleeding "
        "hysterectomy ovarian cyst laparoscopy gynecology gynaecology"
    ),
    "dental treatment": (
        "dental surgery tooth extraction impaction maxilla mandible oral accident dental"
    ),
    "general hospitalisation": (
        "hospitalisation hospitalization inpatient admission medical management "
        "diabetic diabetes mellitus complications hypertension fever infection "
        "pneumonia respiratory systemic illness general medicine acute illness"
    ),
    "excluded": (
        "cosmetic aesthetic liposuction bariatric obesity surgery weight loss gender change "
        "ivf in vitro fertilization surrogacy infertility assisted reproduction experimental "
        "clinical trial self-inflicted substance abuse alcohol drug detox vitamin supplement "
        "spectacles contact lens eyesight correction lasik refractive"
    ),
}

DAYCARE_SCHEDULE: list[str] = [
    "cataract", "phacoemulsification", "lens replacement", "dialysis",
    "haemodialysis", "hemodialysis", "chemotherapy", "radiotherapy",
    "lithotripsy", "tonsillectomy", "adenoidectomy", "sinusitis", "fess",
    "angiography", "angioplasty", "hysteroscopy", "d&c", "fracture",
    "plastering", "hydrocele", "arthroscopy", "colonoscopy", "endoscopy",
    "cholecystectomy", "appendectomy", "hernia", "piles", "fistula",
    "varicocele", "circumcision", "skin lesion", "breast lump", "ganglion",
    "carpal tunnel", "trigger finger", "tympanoplasty", "myringotomy",
    "nasal polypectomy", "septoplasty", "pterygium", "chalazion",
    "abscess", "urethral", "cystoscopy", "turp", "eswl",
]

EXCLUDED_ANCHORS: list[str] = [
    "cosmetic", "aesthetic", "liposuction", "bariatric", "obesity",
    "gender change", "ivf", "infertility", "surrogacy", "experimental",
    "self-inflicted", "substance abuse", "alcohol", "detox", "vitamin",
    "supplement", "spectacles", "contact lens", "contact lenses",
    "eyesight correction", "lasik", "refractive",
]


def is_typo_or_match(word: str, target: str, threshold: float = 0.82, max_len_diff: int = 2) -> bool:
    """Check if word matches target exactly, as a compound root, or via a minor spelling mistake."""
    w = word.lower().strip()
    t = target.lower().strip()
    if w == t:
        return True
    if len(t) >= 6 and t in w:
        return True
    if abs(len(w) - len(t)) > max_len_diff:
        return False
    if len(w) < 3 or len(t) < 3:
        return False
    return difflib.SequenceMatcher(None, w, t).ratio() >= threshold


def match_waiting_condition(
    text: str,
    condition_terms: Sequence[str],
    threshold: float = 0.82,
) -> bool:
    """
    Check if clinical text matches condition terms via exact, fuzzy, or compound phrase matching.
    Distinguishes single-word terms from multi-word terms (e.g. 'contact lens' won't match 'lens replacement').
    """
    cleaned = text.lower().replace("-", " ").replace(",", " ").replace("/", " ")
    words = cleaned.split()

    single_word_terms = [t.lower().strip() for t in condition_terms if len(t.split()) == 1]
    multi_word_terms = [t.lower().strip() for t in condition_terms if len(t.split()) > 1]

    # Single-word terms match against single query words
    for w in words:
        if len(w) < 3:
            continue
        for st in single_word_terms:
            if is_typo_or_match(w, st, threshold=threshold):
                return True

    # Multi-word terms match against query n-grams
    for i in range(len(words) - 1):
        bigram = f"{words[i]} {words[i+1]}"
        for mt in multi_word_terms:
            if abs(len(bigram) - len(mt)) <= 3:
                if difflib.SequenceMatcher(None, bigram, mt).ratio() >= threshold:
                    return True

    return False


class ClinicalTaxonomyClassifier:
    """Semantic vector taxonomy classifier with typo correction and anchor validation."""

    _instance: ClinicalTaxonomyClassifier | None = None

    def __init__(self) -> None:
        self.categories = list(TAXONOMY_PROFILES.keys())
        self.corpus = list(TAXONOMY_PROFILES.values())
        self.category_vocab: dict[str, set[str]] = {
            cat: set(profile.split()) for cat, profile in TAXONOMY_PROFILES.items()
        }
        self.all_vocab = {w for vocab in self.category_vocab.values() for w in vocab}

        # Vectorizer over word unigrams and bigrams
        self.vectorizer = TfidfVectorizer(
            analyzer="word",
            ngram_range=(1, 2),
            sublinear_tf=True,
            lowercase=True,
        )
        self.matrix = self.vectorizer.fit_transform(self.corpus)

    @classmethod
    def get_instance(cls) -> ClinicalTaxonomyClassifier:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _correct_typos(self, text: str) -> str:
        """Resolve minor typos to closest verified medical vocabulary terms."""
        words = text.lower().replace("-", " ").replace(",", " ").replace("/", " ").split()
        corrected = []
        for w in words:
            if w in self.all_vocab:
                corrected.append(w)
                continue
            matched = False
            for target in self.all_vocab:
                if is_typo_or_match(w, target, threshold=0.82):
                    corrected.append(target)
                    matched = True
                    break
            if not matched:
                corrected.append(w)
        return " ".join(corrected)

    def classify(self, text: str) -> tuple[str, float]:
        """
        Classify text against clinical taxonomy.
        Returns (best_category, confidence_score).
        Guarantees: If text has no anchor clinical term, confidence is 0.0 -> unclassified.
        """
        if not text.strip():
            return "unclassified", 0.0

        corrected_text = self._correct_typos(text)
        qv = self.vectorizer.transform([corrected_text])
        sims = cosine_similarity(qv, self.matrix)[0]

        best_idx = int(np.argmax(sims))
        best_score = float(sims[best_idx])
        best_category = self.categories[best_idx]

        # Anchor validation: confirm at least one token actually belongs to the best category's vocabulary
        query_words = set(corrected_text.split())
        has_anchor = bool(query_words & self.category_vocab[best_category])

        if not has_anchor or best_score < 0.10:
            return "unclassified", 0.0

        return best_category, round(best_score, 4)


def check_is_daycare(text: str) -> bool:
    """Check if procedure qualifies as daycare under policy schedule with typo tolerance."""
    return match_waiting_condition(text, DAYCARE_SCHEDULE, threshold=0.82)


def check_is_excluded(text: str) -> bool:
    """Check if text matches permanent policy exclusions with typo tolerance."""
    return match_waiting_condition(text, EXCLUDED_ANCHORS, threshold=0.82)
