import json
import os
from pathlib import Path
from uuid import uuid4

from src.agents.graph import run_workflow
from data_contracts import PreAuthRequest

try:
    from celery import Celery
except ImportError:
    Celery = None

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery_app = (
    Celery("preauth", broker=REDIS_URL, backend=REDIS_URL)
    if Celery and os.getenv("CELERY_ENABLED", "false").lower() == "true"
    else None
)
RESULT_PATH = Path(os.getenv("RESULT_STORE_PATH", "data/results.json"))
_local_results: dict[str, dict] = {}


def _save(task_id: str, value: dict) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    records = json.loads(RESULT_PATH.read_text(encoding="utf-8")) if RESULT_PATH.exists() else {}
    records[task_id] = value
    RESULT_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")


def process_request(payload: dict, task_id: str | None = None) -> str:
    task_id = task_id or str(uuid4())
    response = run_workflow(PreAuthRequest.model_validate(payload))
    result = {"status": "SUCCESS", "result": response.model_dump(mode="json")}
    _local_results[task_id] = result
    _save(task_id, result)
    return task_id


if celery_app:
    @celery_app.task(name="preauth.process")
    def process_request_task(payload: dict, task_id: str) -> str:
        return process_request(payload, task_id)


def enqueue(payload: dict) -> str:
    task_id = str(uuid4())
    if celery_app:
        process_request_task.delay(payload, task_id)
    else:
        process_request(payload, task_id)
    return task_id


def get_result(task_id: str) -> dict | None:
    if task_id in _local_results:
        return _local_results[task_id]
    if RESULT_PATH.exists():
        return json.loads(RESULT_PATH.read_text(encoding="utf-8")).get(task_id)
    return None
