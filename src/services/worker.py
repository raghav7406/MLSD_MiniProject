"""Worker service – Celery task execution with local fallback, retries, and error handling."""
import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from data_contracts import PreAuthRequest
from src.agents.graph import run_workflow
from src.observability.tracing import extract_trace_context, init_tracer, trace_span

logger = logging.getLogger("preauth.worker")
init_tracer(service_name=os.getenv("OTEL_WORKER_SERVICE_NAME", "preauth-worker"))

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
_processed_keys: set[str] = set()


def _save(task_id: str, value: dict) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    records = json.loads(RESULT_PATH.read_text(encoding="utf-8")) if RESULT_PATH.exists() else {}
    records[task_id] = value
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=RESULT_PATH.parent,
        prefix=f"{RESULT_PATH.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        json.dump(records, temporary, indent=2, default=str)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, RESULT_PATH)


def _idempotency_key(payload: dict) -> str:
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


def process_request(
    payload: dict,
    task_id: str | None = None,
    run_id: str | None = None,
    trace_headers: dict | None = None,
) -> str:
    task_id = task_id or str(uuid4())
    run_id = run_id or str(uuid4())
    parent_ctx = extract_trace_context(trace_headers or {}) if trace_headers else None

    # Idempotency check
    idem_key = _idempotency_key(payload)
    if idem_key in _processed_keys:
        logger.info("Duplicate request detected (idempotency key: %s)", idem_key)
        for tid, res in _local_results.items():
            if res.get("idempotency_key") == idem_key:
                _local_results[task_id] = res
                return task_id

    start_time = time.time()
    try:
        request = PreAuthRequest.model_validate(payload)
        response = run_workflow(request, run_id=run_id)
        result = {
            "status": "SUCCESS",
            "result": response.model_dump(mode="json"),
            "run_id": run_id,
            "processing_time_seconds": round(time.time() - start_time, 3),
            "idempotency_key": idem_key,
        }
    except Exception as e:
        logger.error("Workflow failed for task %s: %s", task_id, e)
        result = {
            "status": "FAILED",
            "error": str(e),
            "run_id": run_id,
            "processing_time_seconds": round(time.time() - start_time, 3),
            "idempotency_key": idem_key,
        }

    _local_results[task_id] = result
    with trace_span("preauth.result.persist", attributes={"preauth.run_id": run_id}, parent_context=parent_ctx):
        _save(task_id, result)
    _processed_keys.add(idem_key)
    return task_id


if celery_app:
    @celery_app.task(name="preauth.process", bind=True, max_retries=2, default_retry_delay=5)
    def process_request_task(
        self,
        payload: dict,
        task_id: str,
        run_id: str = "",
        trace_headers: dict | None = None,
    ) -> str:
        headers = trace_headers or getattr(self.request, "headers", None) or {}
        try:
            return process_request(payload, task_id, run_id or str(uuid4()), trace_headers=headers)
        except Exception as exc:
            logger.error("Celery task failed (attempt %d): %s", self.request.retries, exc)
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc)
            _local_results[task_id] = {"status": "FAILED", "error": str(exc), "run_id": run_id}
            _save(task_id, _local_results[task_id])
            return task_id


def enqueue(payload: dict, run_id: str = "", trace_headers: dict | None = None) -> str:
    task_id = str(uuid4())
    run_id = run_id or str(uuid4())
    if celery_app:
        process_request_task.apply_async(
            args=[payload, task_id, run_id, trace_headers or {}],
            headers=trace_headers or {},
        )
    else:
        process_request(payload, task_id, run_id, trace_headers=trace_headers)
    return task_id


def get_result(task_id: str) -> dict | None:
    if task_id in _local_results:
        return _local_results[task_id]
    if RESULT_PATH.exists():
        return json.loads(RESULT_PATH.read_text(encoding="utf-8")).get(task_id)
    return None
