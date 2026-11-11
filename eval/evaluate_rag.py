import json
from pathlib import Path

from data_contracts import AdmissionType, PreAuthRequest
from src.agents.graph import run_workflow


def evaluate(dataset_path: str | Path = "eval/eval_dataset.json") -> dict:
    cases = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    passed = 0
    for case in cases:
        request = PreAuthRequest(
            member_id=case["name"], policy_number="EVAL", policy_name="Care Supreme",
            diagnosis_name=case["diagnosis_name"], procedure_name=case["procedure_name"],
            admission_type=AdmissionType.PLANNED, policy_tenure_months=case["policy_tenure_months"],
            estimated_cost=10000,
        )
        passed += run_workflow(request).recommendation.value == case["expected"]
    return {"cases": len(cases), "passed": passed, "accuracy": passed / len(cases) if cases else 0}


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2))
