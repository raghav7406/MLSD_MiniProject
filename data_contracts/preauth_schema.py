from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AdmissionType(str, Enum):
    PLANNED = "PLANNED"
    EMERGENCY = "EMERGENCY"
    DAYCARE = "DAYCARE"


class Recommendation(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    QUERY = "QUERY"


class PreAuthRequest(BaseModel):
    member_id: str = Field(min_length=1, max_length=100)
    policy_number: str = Field(min_length=1, max_length=100)
    policy_name: str = Field(min_length=1, max_length=200)
    diagnosis_name: str = Field(min_length=1, max_length=500)
    procedure_name: str = Field(min_length=1, max_length=500)
    admission_type: AdmissionType
    policy_tenure_months: int = Field(ge=0, le=120)
    estimated_cost: float = Field(gt=0)


class Citation(BaseModel):
    source: str = Field(min_length=1)
    clause: str = Field(min_length=1)


class PreAuthResponse(BaseModel):
    task_id: str | None = None
    recommendation: Recommendation
    indicative_limit: float = Field(ge=0)
    reason: str = Field(min_length=1)
    citations: list[Citation] = Field(default_factory=list)
    escalation_required: bool = False
    clinical_category: str | None = None
    retrieved_clauses: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
