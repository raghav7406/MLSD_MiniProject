"""
Tests for semantic clinical taxonomy classifier, typo resilience, and fail-safe boundaries.
Verifies that spelling errors do not allow waiting-period claims to slip through to approval.
"""
import pytest
from data_contracts import AdmissionType, PreAuthRequest, Recommendation, Route
from src.agents.clinical_agent import ClinicalAgent
from src.agents.clinical_taxonomy import ClinicalTaxonomyClassifier, match_waiting_condition
from src.agents.graph import run_workflow


def make_preauth(
    diagnosis: str,
    procedure: str,
    tenure: int = 11,
    cost: float = 40000.0,
    admission_type: str = "PLANNED",
) -> PreAuthRequest:
    return PreAuthRequest(
        member_id="M-TEST",
        policy_number="P-TEST",
        policy_name="Care Supreme",
        diagnosis_name=diagnosis,
        procedure_name=procedure,
        admission_type=AdmissionType(admission_type),
        policy_tenure_months=tenure,
        estimated_cost=cost,
        pre_existing_conditions=[],
    )


def test_typo_kidney_stone_rejected_under_24_months():
    """Verify spelling mistake in 'kidney' (e.g. 'kidneyy stone') correctly rejects at 11 months."""
    req = make_preauth(
        diagnosis="kidneyy stone",
        procedure="Lithotripsyy procedure",
        tenure=11,
    )
    resp = run_workflow(req)
    assert resp.recommendation == Recommendation.REJECT
    assert resp.route == Route.MEDICAL_REVIEW
    assert "24" in resp.reason or "waiting" in resp.reason.lower()


def test_typo_cataract_rejected_under_24_months():
    """Verify spelling mistake in 'cataract' (e.g. 'catract') correctly rejects at 11 months."""
    req = make_preauth(
        diagnosis="Senile catract",
        procedure="Phacoemulsifcation with iol",
        tenure=11,
        admission_type="DAYCARE",
    )
    resp = run_workflow(req)
    assert resp.recommendation == Recommendation.REJECT
    assert resp.route == Route.MEDICAL_REVIEW
    assert "24" in resp.reason or "waiting" in resp.reason.lower()


def test_typo_liposuction_escalated_as_exclusion():
    """Verify spelling mistake in 'liposuction' (e.g. 'liposucton') still identifies exclusion."""
    req = make_preauth(
        diagnosis="Adiposity",
        procedure="Liposucton surgery",
        tenure=36,
    )
    resp = run_workflow(req)
    assert resp.recommendation == Recommendation.QUERY
    assert resp.escalation_required is True
    assert "exclusion" in resp.reason.lower()


def test_unknown_condition_fails_safe_to_medical_review():
    """Verify that an unrecognized or unclassified condition NEVER silently approves."""
    req = make_preauth(
        diagnosis="Unspecified unknown rare condition",
        procedure="Novel uncataloged intervention",
        tenure=24,
    )
    resp = run_workflow(req)
    assert resp.recommendation == Recommendation.QUERY
    assert resp.route == Route.MEDICAL_REVIEW
    assert resp.escalation_required is True


def test_lens_replacement_not_confused_with_contact_lens():
    """Verify lens replacement for cataract is covered, not falsely excluded as contact lenses."""
    classifier = ClinicalTaxonomyClassifier.get_instance()
    cat, conf = classifier.classify("cataract lens replacement")
    assert cat == "cataract surgery"
    assert conf > 0.10

