"""Tests for explicit agent architecture, transitions, tools, and verification."""
import time
import pytest
from data_contracts import AdmissionType, Citation, PreAuthRequest, Recommendation, Route
from src.agents import (
    ClinicalAgent,
    CoverageAgent,
    VerificationAgent,
    classify_clinical_request,
    execute_tool,
    reset_store,
    route_after_clinical,
    route_after_coverage,
    route_after_guardrail,
    route_after_verification,
    run_workflow,
    verify_coverage,
    verify_decision,
)
from src.agents.state import AgentState
from src.agents.tools import (
    clause_lookup,
    corpus_search,
    request_field_lookup,
    set_simulated_tool_delay,
    set_simulated_tool_failure,
)


@pytest.fixture(autouse=True)
def cleanup():
    reset_store()
    yield
    reset_store()


def make_request(
    tenure: int = 24,
    procedure: str = "Phacoemulsification",
    diagnosis: str = "Cataract",
    admission_type: AdmissionType = AdmissionType.PLANNED,
    cost: float = 35000.0,
    pre_existing: list[str] | None = None,
) -> PreAuthRequest:
    return PreAuthRequest(
        member_id="M-TEST",
        policy_number="P-TEST",
        policy_name="Care Supreme",
        diagnosis_name=diagnosis,
        procedure_name=procedure,
        admission_type=admission_type,
        policy_tenure_months=tenure,
        estimated_cost=cost,
        pre_existing_conditions=pre_existing or [],
    )


class TestClinicalAgent:
    def test_clinical_agent_classifies_categories(self):
        state: AgentState = {"request": make_request(diagnosis="Cataract", procedure="Lens replacement")}
        out = ClinicalAgent.process(state)
        assert out.clinical_category == "cataract surgery"
        assert out.is_daycare is True
        assert out.is_unsupported is False

    def test_clinical_agent_detects_permanent_exclusion(self):
        state: AgentState = {"request": make_request(diagnosis="Cosmetic", procedure="Liposuction")}
        out = ClinicalAgent.process(state)
        assert out.clinical_category == "excluded"
        assert out.is_unsupported is True
        assert "exclusion" in out.escalation_reason.lower()

    def test_clinical_agent_detects_pre_existing_conditions(self):
        state: AgentState = {"request": make_request(pre_existing=["Diabetes Mellitus"])}
        out = ClinicalAgent.process(state)
        assert out.has_pre_existing is True

    def test_clinical_agent_flags_daycare_mismatch(self):
        state: AgentState = {
            "request": make_request(
                diagnosis="Complex condition",
                procedure="Unheard-of surgery XYZ",
                admission_type=AdmissionType.DAYCARE,
            )
        }
        out = ClinicalAgent.process(state)
        assert out.is_unsupported is True
        assert "day-care" in out.escalation_reason.lower()

    def test_clinical_agent_never_approves_directly(self):
        state: AgentState = {"request": make_request(tenure=36)}
        state = classify_clinical_request(state)
        assert "recommendation" not in state or state["recommendation"] != "APPROVE"


class TestToolRunner:
    def test_execute_tool_corpus_search(self):
        state: AgentState = {"run_id": "test-run", "max_tool_calls": 20}
        res = execute_tool(state, "corpus_search", "cataract surgery coverage", purpose="test search")
        assert res["success"] is True
        assert res["result_count"] > 0
        assert res["tool"] == "corpus_search"
        assert len(state["tool_calls"]) == 1
        assert state["total_tool_calls"] == 1

    def test_execute_tool_clause_lookup(self):
        state: AgentState = {"run_id": "test-run", "max_tool_calls": 20}
        res = execute_tool(state, "clause_lookup", "Code-Excl02", purpose="lookup exclusion code")
        assert res["success"] is True
        assert res["result_count"] > 0
        assert res["tool"] == "clause_lookup"

    def test_execute_tool_request_field_lookup(self):
        req = make_request(diagnosis="Cataract")
        state: AgentState = {"request": req, "run_id": "test-run", "max_tool_calls": 20}
        res = execute_tool(state, "request_field_lookup", "diagnosis_name", purpose="lookup diagnosis")
        assert res["success"] is True
        assert res["results"][0]["value"] == "Cataract"

    def test_execute_tool_enforces_max_tool_calls(self):
        state: AgentState = {"run_id": "test-run", "max_tool_calls": 2, "total_tool_calls": 2}
        res = execute_tool(state, "corpus_search", "test query")
        assert res["success"] is False
        assert "exceeded" in res["error"].lower()

    def test_execute_tool_handles_simulated_failure(self):
        set_simulated_tool_failure("corpus_search", "Connection to storage backend timed out")
        state: AgentState = {"run_id": "test-run", "max_tool_calls": 20}
        res = execute_tool(state, "corpus_search", "test query")
        assert res["success"] is False
        assert "Connection to storage backend timed out" in res["error"]

    def test_execute_tool_handles_timeout(self):
        set_simulated_tool_delay(0.2)
        state: AgentState = {"run_id": "test-run", "max_tool_calls": 20}
        res = execute_tool(state, "corpus_search", "test query", timeout_seconds=0.05)
        assert res["success"] is False
        assert "timed out" in res["error"].lower()


class TestGraphTransitionsAndBounds:
    def test_named_route_transitions(self):
        clean_state: AgentState = {}
        assert route_after_guardrail(clean_state) == "clinical"

        guardrail_state: AgentState = {"escalation_required": True, "reason": "guardrail injection"}
        assert route_after_guardrail(guardrail_state) == "escalate_guardrail"

        clinical_state: AgentState = {"clinical_category": "cataract surgery"}
        assert route_after_clinical(clinical_state) == "coverage"

        coverage_state: AgentState = {"recommendation": "APPROVE"}
        assert route_after_coverage(coverage_state) == "verification"

        verified_state: AgentState = {"verification_passed": True}
        assert route_after_verification(verified_state) == "final_response"

        retry_state: AgentState = {"verification_passed": False, "verification_attempts": 1}
        assert route_after_verification(retry_state) == "alternate_search"

        escalated_state: AgentState = {"verification_passed": False, "verification_attempts": 2}
        assert route_after_verification(escalated_state) == "escalate_verification"

    def test_simulated_tool_failure_escalates_safely(self):
        set_simulated_tool_failure("corpus_search", "Backend offline")
        resp = run_workflow(make_request(tenure=24))
        assert resp.recommendation == Recommendation.QUERY
        assert resp.route == Route.MEDICAL_REVIEW
        assert resp.escalation_required is True
        assert "tool error" in resp.reason.lower() or "retrieval" in resp.reason.lower()

    def test_tool_call_limit_breached_escalates_safely(self):
        req = make_request(tenure=24)
        # Override run_workflow bounds by setting max_tool_calls low
        state: AgentState = {
            "request": req,
            "clinical_category": "cataract surgery",
            "run_id": "bound-test",
            "max_tool_calls": 1,
            "steps": 0,
            "max_steps": 10,
            "total_tool_calls": 1,
            "tool_calls": [],
            "step_timings": {},
            "trace_events": [],
            "start_time": time.time(),
            "deadline_seconds": 30.0,
        }
        resp = CoverageAgent.evaluate(state)
        assert resp["recommendation"] == Recommendation.QUERY.value
        assert resp["escalation_required"] is True

    def test_max_steps_breached_escalates_safely(self):
        req = make_request(tenure=24)
        # Force steps to 15
        state: AgentState = {
            "request": req,
            "run_id": "steps-test",
            "steps": 15,
            "max_steps": 10,
            "total_tool_calls": 0,
            "max_tool_calls": 20,
            "start_time": time.time(),
            "deadline_seconds": 30.0,
        }
        from src.agents.graph import _check_bounds
        bound = _check_bounds(state)
        assert bound is not None
        assert "Maximum steps exceeded" in bound

    def test_deadline_breached_escalates_safely(self):
        req = make_request(tenure=24)
        # Force start time in the past
        state: AgentState = {
            "request": req,
            "run_id": "deadline-test",
            "steps": 1,
            "max_steps": 10,
            "total_tool_calls": 0,
            "max_tool_calls": 20,
            "start_time": time.time() - 35.0,
            "deadline_seconds": 30.0,
        }
        from src.agents.graph import _check_bounds
        bound = _check_bounds(state)
        assert bound is not None
        assert "Execution deadline exceeded" in bound


class TestVerificationNodeAndRetry:
    def test_ungrounded_citation_triggers_retry_then_escalation(self):
        state: AgentState = {
            "request": make_request(tenure=24),
            "retrieved_clauses": [{"text": "Actual policy clause regarding cataract."}],
            "citations": [Citation(source="test.txt", clause="Completely fabricated citation not in retrieved clauses.")],
            "recommendation": "APPROVE",
            "verification_attempts": 0,
            "max_tool_calls": 20,
            "step_timings": {},
        }
        # First pass: detects ungrounded citation, runs alternate search, sets attempt = 1
        state = VerificationAgent.verify(state)
        assert state["verification_passed"] is False
        assert state["verification_attempts"] == 1
        assert len(state["verification_issues"]) > 0

        # Second pass: re-evaluates; still ungrounded -> escalates to QUERY
        state = VerificationAgent.verify(state)
        assert state["verification_passed"] is False
        assert state["verification_attempts"] == 2
        assert state["recommendation"] == Recommendation.QUERY.value
        assert state["escalation_required"] is True
        assert state["route"] == "medical-review"

    def test_approval_without_citations_escalates(self):
        state: AgentState = {
            "request": make_request(tenure=24),
            "retrieved_clauses": [{"text": "Some clause"}],
            "citations": [],
            "recommendation": "APPROVE",
            "verification_attempts": 1,  # final attempt
            "step_timings": {},
        }
        state = VerificationAgent.verify(state)
        assert state["verification_passed"] is False
        assert state["recommendation"] == Recommendation.QUERY.value
        assert state["escalation_required"] is True


class TestTraceReconstruction:
    def test_trace_contains_all_agents_and_handoffs(self):
        resp = run_workflow(make_request(tenure=24))
        assert resp.recommendation == Recommendation.APPROVE
        assert "trace_events" in resp.metadata
        trace = resp.metadata["trace_events"]
        assert len(trace) >= 3

        nodes = [ev["node"] for ev in trace]
        assert "input_guardrails" in nodes
        assert "clinical_intake" in nodes
        assert "coverage_decision" in nodes

        agents = [ev["agent_name"] for ev in trace]
        assert ClinicalAgent.name in agents
        assert CoverageAgent.name in agents

        # Verify tool calls are tracked with duration and results
        tool_calls = resp.metadata.get("tool_calls", [])
        assert len(tool_calls) >= 3
        for call in tool_calls:
            assert "tool" in call
            assert "duration_seconds" in call
            assert "success" in call
            assert "run_id" in call

    def test_generate_all_presentation_traces(self, tmp_path):
        from src.agents.trace_formatter import generate_all_traces
        traces = generate_all_traces(output_dir=tmp_path)
        assert len(traces) == 5
        for t in traces:
            assert "run_id" in t
            assert "recommendation" in t
            assert "route" in t
            assert "trace_events" in t
            assert "tool_calls" in t
