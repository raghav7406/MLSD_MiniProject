"""API service – REST endpoints, metrics, rate limiting, caching, feedback."""
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app

from data_contracts import PreAuthRequest
from .cache import result_cache
from .circuit_breaker import provider_breaker
from .quarantine import quarantine_payload
from .rate_limiter import rate_limiter
from .worker import enqueue, get_result

logger = logging.getLogger("preauth.api")

app = FastAPI(title="Health Insurance Pre-Authorisation Desk", version="2.0.0")

# ── Prometheus metrics ──────────────────────────────────────────────────────────
request_count = Counter("preauth_requests_total", "Pre-authorisation requests", ["status"])
error_count = Counter("preauth_errors_total", "Errors by type", ["type"])
escalation_count = Counter("preauth_escalations_total", "Escalated requests")
request_latency = Histogram(
    "preauth_request_latency_seconds",
    "Request latency",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)
step_latency = Histogram("preauth_step_latency_seconds", "Per-step latency", ["step"])
tool_calls_total = Counter("preauth_tool_calls_total", "Total tool calls")
retry_count = Counter("preauth_retries_total", "Retry count")
circuit_state = Gauge(
    "preauth_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half-open)",
)
queue_depth = Gauge("preauth_queue_depth", "Pending tasks")
cache_hits = Counter("preauth_cache_hits_total", "Cache hits")
cache_misses = Counter("preauth_cache_misses_total", "Cache misses")
worker_uptime = Gauge("preauth_worker_uptime_seconds", "Worker uptime")
ingestion_freshness = Gauge("preauth_ingestion_freshness_seconds", "Seconds since last ingestion")

_start_time = time.time()
app.mount("/metrics", make_asgi_app())


# ── Health endpoint ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": round(time.time() - _start_time, 1),
        "circuit_breaker": provider_breaker.state,
        "cache_stats": result_cache.stats,
    }


# ── Validation error handler ───────────────────────────────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    if request.url.path == "/api/v1/preauth":
        try:
            payload = json.loads(await request.body())
        except json.JSONDecodeError:
            payload = {"raw_body": (await request.body()).decode("utf-8", errors="replace")}
        quarantine_payload(payload, str(exc.errors()))
        error_count.labels(type="validation").inc()
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


# ── Submit pre-auth ─────────────────────────────────────────────────────────────
@app.post("/api/v1/preauth", status_code=202)
async def submit_preauth(request: Request, payload: PreAuthRequest) -> dict:
    # Rate limiting
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.allow(client_ip):
        error_count.labels(type="rate_limited").inc()
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    # Check cache
    payload_dict = payload.model_dump(mode="json")
    cached = result_cache.get(payload_dict)
    if cached is not None:
        cache_hits.inc()
        return cached
    cache_misses.inc()

    correlation_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    request_count.labels(status="submitted").inc()
    with request_latency.time():
        task_id = enqueue(payload_dict, run_id=run_id)

    queue_depth.inc()
    response = {
        "task_id": task_id,
        "run_id": run_id,
        "correlation_id": correlation_id,
        "status": "PENDING",
    }
    # Cache the submission response for idempotency
    result_cache.put(payload_dict, response)
    return response


# ── Poll result ─────────────────────────────────────────────────────────────────
@app.get("/api/v1/preauth/{task_id}")
async def preauth_status(task_id: str) -> dict:
    result = get_result(task_id)
    if result is None:
        return {"task_id": task_id, "status": "PENDING"}

    if result.get("status") == "SUCCESS":
        request_count.labels(status="success").inc()
        res = result.get("result", {})
        if res.get("escalation_required"):
            escalation_count.inc()
        for step_name, duration in res.get("step_timings", {}).items():
            step_latency.labels(step=step_name).observe(duration)
        tool_call_count = res.get("metadata", {}).get("tool_calls", 0)
        if tool_call_count:
            tool_calls_total.inc(tool_call_count)
    elif result.get("status") == "FAILED":
        request_count.labels(status="failed").inc()
        error_count.labels(type="workflow_failure").inc()

    state_map = {"CLOSED": 0, "OPEN": 1, "HALF_OPEN": 2}
    circuit_state.set(state_map.get(provider_breaker.state, 0))
    worker_uptime.set(round(time.time() - _start_time, 1))

    return {"task_id": task_id, **result}


# ── Feedback endpoint ───────────────────────────────────────────────────────────
@app.post("/api/v1/feedback")
async def submit_feedback(request: Request) -> dict:
    body = await request.json()
    run_id = body.get("run_id", "")
    satisfactory = body.get("satisfactory")
    reason = body.get("reason", "")

    if not run_id:
        raise HTTPException(status_code=400, detail="run_id is required")
    if satisfactory is None:
        raise HTTPException(status_code=400, detail="satisfactory (bool) is required")

    feedback_path = Path(os.getenv("FEEDBACK_PATH", "data/feedback.json"))
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    records = json.loads(feedback_path.read_text(encoding="utf-8")) if feedback_path.exists() else []
    records.append({
        "run_id": run_id,
        "satisfactory": satisfactory,
        "reason": reason,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    })
    feedback_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return {"status": "recorded", "run_id": run_id}


# ── Feedback summary ────────────────────────────────────────────────────────────
@app.get("/api/v1/feedback/summary")
async def feedback_summary() -> dict:
    feedback_path = Path(os.getenv("FEEDBACK_PATH", "data/feedback.json"))
    if not feedback_path.exists():
        return {"total": 0, "satisfactory": 0, "unsatisfactory": 0, "satisfaction_rate": 0.0}
    records = json.loads(feedback_path.read_text(encoding="utf-8"))
    total = len(records)
    sat = sum(1 for r in records if r.get("satisfactory"))
    return {
        "total": total,
        "satisfactory": sat,
        "unsatisfactory": total - sat,
        "satisfaction_rate": round(sat / total, 3) if total else 0.0,
    }
