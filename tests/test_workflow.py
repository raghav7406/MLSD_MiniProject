from data_contracts import AdmissionType, PreAuthRequest
from src.agents.graph import run_workflow


def request(tenure: int, procedure: str = "Phacoemulsification") -> PreAuthRequest:
    return PreAuthRequest(
        member_id="M1", policy_number="P1", policy_name="Care Supreme",
        diagnosis_name="Cataract", procedure_name=procedure,
        admission_type=AdmissionType.PLANNED, policy_tenure_months=tenure,
        estimated_cost=50000,
    )


def test_cataract_waiting_period_rejects_eleven_months():
    assert run_workflow(request(11)).recommendation.value == "REJECT"


def test_cataract_after_waiting_period_approves():
    assert run_workflow(request(24)).recommendation.value == "APPROVE"
