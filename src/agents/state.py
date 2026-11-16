from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from data_contracts import PreAuthRequest


class ToolCall(TypedDict):
    tool: str
    query: str
    purpose: str
    result_count: int
    duration_seconds: float
    success: bool
    error: str | None
    retry_number: int
    run_id: str


class TraceEvent(TypedDict):
    step_number: int
    node: str
    agent_name: str
    agent_status: str
    transition_to: str
    handoff_reason: str
    duration_seconds: float
    timestamp: str


@dataclass
class ClinicalOutput:
    clinical_category: str
    admission_classification: str
    is_daycare: bool
    has_pre_existing: bool
    is_unsupported: bool
    escalation_reason: str = ""
    duration_seconds: float = 0.0


@dataclass
class CoverageOutput:
    clinical_category: str
    base_clauses: list[dict]
    exclusion_clauses: list[dict]
    sublimit_clauses: list[dict]
    daycare_clauses: list[dict]
    retrieved_clauses: list[dict]
    provisional_recommendation: str
    provisional_route: str
    reason: str
    indicative_limit: float
    citations: list[Any]
    escalation_required: bool
    duration_seconds: float = 0.0


@dataclass
class VerificationOutput:
    verification_passed: bool
    verification_attempts: int
    verification_issues: list[str]
    final_recommendation: str
    final_route: str
    final_reason: str
    final_limit: float
    escalation_required: bool
    duration_seconds: float = 0.0


class AgentState(TypedDict, total=False):
    # Input
    request: PreAuthRequest
    run_id: str
    correlation_id: str

    # Classification (Clinical Agent)
    clinical_category: str
    admission_classification: str
    is_daycare: bool
    has_pre_existing: bool
    is_unsupported: bool

    # Retrieval (Coverage Agent)
    base_clauses: list
    exclusion_clauses: list
    sublimit_clauses: list
    daycare_clauses: list
    retrieved_clauses: list

    # Decision (Coverage Agent provisional / Verification Agent final)
    recommendation: str
    reason: str
    indicative_limit: float
    citations: list
    route: str
    escalation_required: bool
    escalation_reason: str

    # Verification (Verification Agent)
    verification_passed: bool
    verification_attempts: int
    verification_issues: list[str]

    # Tracking & Bounds
    steps: int
    max_steps: int
    tool_calls: list[ToolCall]
    total_tool_calls: int
    max_tool_calls: int
    step_timings: dict[str, float]
    trace_events: list[TraceEvent]
    start_time: float
    deadline_seconds: float

    # Agent Metadata
    current_agent: str
    current_status: str

    # LLMOps
    prompt_version: str
    token_usage: dict[str, int]
    cost_usd: float

    # Error handling
    error: str | None
    fallback_used: bool
