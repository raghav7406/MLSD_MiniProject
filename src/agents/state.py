from __future__ import annotations

from typing import TypedDict, Any

from data_contracts import PreAuthRequest


class ToolCall(TypedDict):
    tool: str
    query: str
    result_count: int
    duration_seconds: float


class AgentState(TypedDict, total=False):
    # Input
    request: PreAuthRequest
    run_id: str
    correlation_id: str
    # Classification
    clinical_category: str
    admission_classification: str
    is_daycare: bool
    has_pre_existing: bool
    is_unsupported: bool
    # Retrieval
    base_clauses: list
    exclusion_clauses: list
    sublimit_clauses: list
    daycare_clauses: list
    retrieved_clauses: list
    # Decision
    recommendation: str
    reason: str
    indicative_limit: float
    citations: list
    route: str
    escalation_required: bool
    escalation_reason: str
    # Verification
    verification_passed: bool
    verification_attempts: int
    verification_issues: list[str]
    # Tracking
    steps: int
    max_steps: int
    tool_calls: list[ToolCall]
    total_tool_calls: int
    max_tool_calls: int
    step_timings: dict[str, float]
    start_time: float
    deadline_seconds: float
    # LLMOps
    prompt_version: str
    token_usage: dict[str, int]
    cost_usd: float
    # Error handling
    error: str | None
    fallback_used: bool
