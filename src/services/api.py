import json

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, make_asgi_app

from data_contracts import PreAuthRequest
from .quarantine import quarantine_payload
from .worker import enqueue, get_result

app = FastAPI(title="Health Insurance Pre-Authorisation Desk", version="1.0.0")
request_count = Counter("preauth_requests_total", "Pre-authorisation requests")
request_latency = Histogram("preauth_request_latency_seconds", "Request latency")
app.mount("/metrics", make_asgi_app())


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    if request.url.path == "/api/v1/preauth":
        try:
            payload = json.loads(await request.body())
        except json.JSONDecodeError:
            payload = {"raw_body": (await request.body()).decode("utf-8", errors="replace")}
        quarantine_payload(payload, str(exc))
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.post("/api/v1/preauth", status_code=202)
async def submit_preauth(payload: PreAuthRequest) -> dict[str, str]:
    request_count.inc()
    with request_latency.time():
        return {"task_id": enqueue(payload.model_dump(mode="json"))}


@app.get("/api/v1/preauth/{task_id}")
async def preauth_status(task_id: str) -> dict:
    result = get_result(task_id)
    if result is None:
        return {"task_id": task_id, "status": "PENDING"}
    return {"task_id": task_id, **result}
