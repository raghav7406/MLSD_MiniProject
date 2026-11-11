from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class AdmissionType(str, Enum):
    PLANNED = "PLANNED"
    EMERGENCY = "EMERGENCY"
    DAYCARE = "DAYCARE"


class Recommendation(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    QUERY = "QUERY"


class Route(str, Enum):
    APPROVE_RECOMMENDED = "approve-recommended"
    QUERY_TO_HOSPITAL = "query-to-hospital"
    MEDICAL_REVIEW = "medical-review"


class RunStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    TIMEOUT = "TIMEOUT"


class PreAuthRequest(BaseModel):
    member_id: str = Field(min_length=1, max_length=100)
    policy_number: str = Field(min_length=1, max_length=100)
    policy_name: str = Field(min_length=1, max_length=200)
    diagnosis_name: str = Field(min_length=1, max_length=500)
    procedure_name: str = Field(min_length=1, max_length=500)
    admission_type: AdmissionType
    policy_tenure_months: int = Field(ge=0, le=120)
    estimated_cost: float = Field(gt=0)
    hospital_name: str = Field(default="", max_length=300)
    treating_doctor: str = Field(default="", max_length=200)
    patient_age: int = Field(default=0, ge=0, le=120)
    pre_existing_conditions: list[str] = Field(default_factory=list)
    sum_insured: float = Field(default=500000.0, gt=0)
    room_category: str = Field(default="General", max_length=100)

    @model_validator(mode="after")
    def cross_field_checks(self):
        if self.estimated_cost > self.sum_insured:
            raise ValueError("estimated_cost cannot exceed sum_insured")
        if self.admission_type == AdmissionType.DAYCARE and self.estimated_cost > 200000:
            raise ValueError("DAYCARE estimated_cost should not exceed 200000")
        return self


class Citation(BaseModel):
    source: str = Field(min_length=1)
    clause: str = Field(min_length=1)


class PreAuthResponse(BaseModel):
    task_id: str | None = None
    run_id: str = Field(default="")
    recommendation: Recommendation
    route: Route = Route.QUERY_TO_HOSPITAL
    indicative_limit: float = Field(ge=0)
    reason: str = Field(min_length=1)
    citations: list[Citation] = Field(default_factory=list)
    escalation_required: bool = False
    clinical_category: str | None = None
    retrieved_clauses: list[str] = Field(default_factory=list)
    verification_passed: bool = False
    prompt_version: str = Field(default="v1")
    token_usage: dict[str, int] = Field(default_factory=dict)
    cost_usd: float = Field(default=0.0, ge=0)
    step_timings: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


def recommendation_to_route(rec: Recommendation, escalation: bool = False) -> Route:
    if escalation:
        return Route.MEDICAL_REVIEW
    mapping = {
        Recommendation.APPROVE: Route.APPROVE_RECOMMENDED,
        Recommendation.REJECT: Route.MEDICAL_REVIEW,
        Recommendation.QUERY: Route.QUERY_TO_HOSPITAL,
    }
    return mapping.get(rec, Route.QUERY_TO_HOSPITAL)
