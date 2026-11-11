"""
LLM stub service – returns deterministic fixed responses for load testing.
Run as: uvicorn services.llm_stub.main:app --port 9000
"""
import time
import uuid

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="LLM Stub", version="1.0.0")

STUB_DELAY_SECONDS = 0.05  # Realistic ~50ms model latency


class CompletionRequest(BaseModel):
    prompt: str = ""
    model: str = "stub"
    max_tokens: int = 500


@app.post("/v1/completions")
async def completions(req: CompletionRequest):
    time.sleep(STUB_DELAY_SECONDS)
    return {
        "id": f"stub-{uuid.uuid4()}",
        "object": "text_completion",
        "model": req.model,
        "choices": [
            {
                "text": (
                    "Recommendation: APPROVE\n"
                    "Reason: The request meets coverage requirements based on retrieved clauses.\n"
                    "Indicative Limit: 50000\n"
                    "Escalation Required: No"
                ),
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 150, "completion_tokens": 50, "total_tokens": 200},
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "llm-stub"}

