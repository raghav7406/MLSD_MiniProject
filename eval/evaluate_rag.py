"""
Batch evaluation runner with LLMOps metrics.

Metrics computed:
- Groundedness: % of claims supported by retrieved passages
- Context relevance: % of retrieved passages relevant to the request
- Faithfulness: answer consistent with retrieved context
- Hallucination rate: unsupported claims / total claims
- Pass/fail accuracy
- Latency per case
- Token usage and cost
"""
import argparse
import json
import time
from pathlib import Path

from data_contracts import AdmissionType, PreAuthRequest
from src.agents.graph import run_workflow


def _build_request(case: dict) -> PreAuthRequest | None:
    """Build a PreAuthRequest from an eval case. Returns None for expected validation errors."""
    try:
        return PreAuthRequest(
            member_id=case.get("member_id_override", case.get("name", "EVAL")),
            policy_number="EVAL-001",
            policy_name="Care Supreme",
            diagnosis_name=case["diagnosis_name"],
            procedure_name=case["procedure_name"],
            admission_type=AdmissionType(case.get("admission_type", "PLANNED")),
            policy_tenure_months=case["policy_tenure_months"],
            estimated_cost=case["estimated_cost"],
            pre_existing_conditions=case.get("pre_existing_conditions", []),
            sum_insured=case.get("sum_insured", 500000.0),
            room_category=case.get("room_category", "General"),
        )
    except (ValueError, Exception):
        return None


def _check_groundedness(response) -> float:
    """What fraction of citations are grounded in retrieved clauses?"""
    citations = response.citations
    retrieved = set(response.retrieved_clauses)
    if not citations:
        return 1.0  # No claims to verify
    grounded = sum(1 for c in citations if c.clause in retrieved)
    return grounded / len(citations)


def _check_context_relevance(case: dict, response) -> float:
    """What fraction of retrieved passages mention the procedure or diagnosis?"""
    clauses = response.retrieved_clauses
    if not clauses:
        return 0.0
    keywords = {case["procedure_name"].lower(), case["diagnosis_name"].lower()}
    relevant = sum(1 for c in clauses if any(kw in c.lower() for kw in keywords))
    return relevant / len(clauses)


def _check_faithfulness(response) -> float:
    """Is the answer consistent with the retrieved context? (simplified: check recommendation is cited)"""
    if response.recommendation.value in ("QUERY",):
        return 1.0  # Queries are always faithful (conservative)
    if response.citations:
        return 1.0
    return 0.0  # Approval/rejection without citations is unfaithful


def _hallucination_rate(response) -> float:
    """Fraction of unsupported claims."""
    return 1.0 - _check_groundedness(response)


def evaluate(
    dataset_path: str | Path = "eval/eval_dataset.json",
    prompt_version: str = "v1",
    report_path: str | Path | None = None,
) -> dict:
    """Run the evaluation suite and return metrics."""
    cases = json.loads(Path(dataset_path).read_text(encoding="utf-8"))

    results = []
    passed = 0
    total_groundedness = 0.0
    total_context_relevance = 0.0
    total_faithfulness = 0.0
    total_hallucination = 0.0
    total_latency = 0.0
    valid_cases = 0

    for case in cases:
        case_result = {"name": case["name"], "expected": case["expected"]}
        start = time.time()

        # Handle expected validation errors
        if case.get("expect_validation_error"):
            request = _build_request(case)
            if request is None:
                case_result["actual"] = "VALIDATION_ERROR"
                case_result["passed"] = True
                case_result["latency_seconds"] = round(time.time() - start, 4)
                passed += 1
            else:
                case_result["actual"] = "UNEXPECTED_VALID"
                case_result["passed"] = False
                case_result["latency_seconds"] = round(time.time() - start, 4)
            results.append(case_result)
            continue

        request = _build_request(case)
        if request is None:
            case_result["actual"] = "BUILD_ERROR"
            case_result["passed"] = False
            results.append(case_result)
            continue

        try:
            response = run_workflow(request, prompt_version=prompt_version)
            latency = time.time() - start

            actual = response.recommendation.value
            case_result["actual"] = actual
            case_result["route"] = response.route.value
            case_result["escalation_required"] = response.escalation_required
            case_result["reason"] = response.reason
            case_result["latency_seconds"] = round(latency, 4)
            case_result["citations_count"] = len(response.citations)
            case_result["retrieved_count"] = len(response.retrieved_clauses)
            case_result["verification_passed"] = response.verification_passed

            # Compute metrics
            groundedness = _check_groundedness(response)
            context_rel = _check_context_relevance(case, response)
            faithfulness = _check_faithfulness(response)
            hallucination = _hallucination_rate(response)

            case_result["groundedness"] = round(groundedness, 3)
            case_result["context_relevance"] = round(context_rel, 3)
            case_result["faithfulness"] = round(faithfulness, 3)
            case_result["hallucination_rate"] = round(hallucination, 3)

            total_groundedness += groundedness
            total_context_relevance += context_rel
            total_faithfulness += faithfulness
            total_hallucination += hallucination
            total_latency += latency
            valid_cases += 1

            case_result["passed"] = actual == case["expected"]
            if case_result["passed"]:
                passed += 1

            # Check expected passages
            if case.get("expected_passages"):
                found = []
                all_text = " ".join(response.retrieved_clauses).lower()
                for passage in case["expected_passages"]:
                    found.append(passage.lower() in all_text)
                case_result["expected_passages_found"] = sum(found)
                case_result["expected_passages_total"] = len(case["expected_passages"])

        except Exception as e:
            case_result["actual"] = "ERROR"
            case_result["error"] = str(e)
            case_result["passed"] = False
            case_result["latency_seconds"] = round(time.time() - start, 4)

        results.append(case_result)

    total = len(cases)
    n = max(valid_cases, 1)
    summary = {
        "prompt_version": prompt_version,
        "total_cases": total,
        "passed": passed,
        "failed": total - passed,
        "accuracy": round(passed / total, 3) if total else 0.0,
        "avg_groundedness": round(total_groundedness / n, 3),
        "avg_context_relevance": round(total_context_relevance / n, 3),
        "avg_faithfulness": round(total_faithfulness / n, 3),
        "avg_hallucination_rate": round(total_hallucination / n, 3),
        "avg_latency_seconds": round(total_latency / n, 4),
        "total_latency_seconds": round(total_latency, 3),
    }

    report = {"summary": summary, "results": results}

    if report_path:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"Report written to {report_path}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate the PreAuth RAG pipeline")
    parser.add_argument("--dataset", default="eval/eval_dataset.json")
    parser.add_argument("--report", default="results/evaluation.json")
    parser.add_argument("--prompt-version", default="v1")
    args = parser.parse_args()

    report = evaluate(args.dataset, args.prompt_version, args.report)
    print(json.dumps(report["summary"], indent=2))
