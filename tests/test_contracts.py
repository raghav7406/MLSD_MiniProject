"""Tests for data contracts and schema validation."""
import pytest
from pydantic import ValidationError

from data_contracts import (
    AdmissionType,
    Citation,
    PreAuthRequest,
    PreAuthResponse,
    Recommendation,
    Route,
    RunStatus,
    recommendation_to_route,
)


class TestPreAuthRequest:
    def test_valid_request(self):
        req = PreAuthRequest(
            member_id="M1", policy_number="P1", policy_name="Care Supreme",
            diagnosis_name="Cataract", procedure_name="Phacoemulsification",
            admission_type=AdmissionType.PLANNED, policy_tenure_months=24,
            estimated_cost=50000,
        )
        assert req.member_id == "M1"
        assert req.admission_type == AdmissionType.PLANNED

    def test_empty_member_id_rejected(self):
        with pytest.raises(ValidationError):
            PreAuthRequest(
                member_id="", policy_number="P1", policy_name="Care Supreme",
                diagnosis_name="Test", procedure_name="Test",
                admission_type=AdmissionType.PLANNED, policy_tenure_months=12,
                estimated_cost=10000,
            )

    def test_cost_exceeds_sum_insured(self):
        with pytest.raises(ValidationError, match="estimated_cost cannot exceed sum_insured"):
            PreAuthRequest(
                member_id="M1", policy_number="P1", policy_name="Test",
                diagnosis_name="Test", procedure_name="Test",
                admission_type=AdmissionType.PLANNED, policy_tenure_months=12,
                estimated_cost=600000, sum_insured=500000,
            )

    def test_daycare_cost_too_high(self):
        with pytest.raises(ValidationError, match="DAYCARE estimated_cost should not exceed 200000"):
            PreAuthRequest(
                member_id="M1", policy_number="P1", policy_name="Test",
                diagnosis_name="Test", procedure_name="Test",
                admission_type=AdmissionType.DAYCARE, policy_tenure_months=12,
                estimated_cost=250000,
            )

    def test_defaults_applied(self):
        req = PreAuthRequest(
            member_id="M1", policy_number="P1", policy_name="Test",
            diagnosis_name="Test", procedure_name="Test",
            admission_type=AdmissionType.PLANNED, policy_tenure_months=12,
            estimated_cost=10000,
        )
        assert req.sum_insured == 500000.0
        assert req.room_category == "General"
        assert req.pre_existing_conditions == []


class TestPreAuthResponse:
    def test_response_creation(self):
        resp = PreAuthResponse(
            run_id="run-1", recommendation=Recommendation.APPROVE,
            route=Route.APPROVE_RECOMMENDED, indicative_limit=50000.0,
            reason="Approved", verification_passed=True,
        )
        assert resp.run_id == "run-1"
        assert resp.route == Route.APPROVE_RECOMMENDED


class TestRouteMapping:
    def test_approve_maps_to_approve_recommended(self):
        assert recommendation_to_route(Recommendation.APPROVE) == Route.APPROVE_RECOMMENDED

    def test_reject_maps_to_medical_review(self):
        assert recommendation_to_route(Recommendation.REJECT) == Route.MEDICAL_REVIEW

    def test_query_maps_to_query_to_hospital(self):
        assert recommendation_to_route(Recommendation.QUERY) == Route.QUERY_TO_HOSPITAL

    def test_escalation_overrides_to_medical_review(self):
        assert recommendation_to_route(Recommendation.APPROVE, escalation=True) == Route.MEDICAL_REVIEW


class TestEnums:
    def test_route_values(self):
        assert Route.APPROVE_RECOMMENDED.value == "approve-recommended"
        assert Route.QUERY_TO_HOSPITAL.value == "query-to-hospital"
        assert Route.MEDICAL_REVIEW.value == "medical-review"

    def test_run_status_values(self):
        assert RunStatus.PENDING.value == "PENDING"
        assert RunStatus.FAILED.value == "FAILED"
        assert RunStatus.TIMEOUT.value == "TIMEOUT"

