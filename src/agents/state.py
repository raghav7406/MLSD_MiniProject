from typing import TypedDict

from data_contracts import PreAuthRequest


class AgentState(TypedDict, total=False):
    request: PreAuthRequest
    clinical_category: str
    base_clauses: list
    exclusion_clauses: list
    retrieved_clauses: list
    recommendation: str
    reason: str
    indicative_limit: float
    citations: list
    escalation_required: bool
    steps: int
