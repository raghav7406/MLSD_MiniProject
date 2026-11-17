from __future__ import annotations

import time
from typing import Any

from src.ingestion.vector_store import VectorStore
from src.observability.tracing import record_exception, trace_span

_store: VectorStore | None = None
_simulated_failure: dict[str, str] = {}
_simulated_delay: float = 0.0


def _get_store(path: str = "data/vector_store.json") -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore(path)
    return _store


def reset_store() -> None:
    """Reset the cached store and simulation hooks (useful for testing)."""
    global _store, _simulated_failure, _simulated_delay
    _store = None
    _simulated_failure = {}
    _simulated_delay = 0.0


def set_simulated_tool_failure(tool_name: str, error_message: str) -> None:
    """Simulate tool failure for testing."""
    global _simulated_failure
    _simulated_failure[tool_name] = error_message


def set_simulated_tool_delay(delay_seconds: float) -> None:
    """Simulate tool execution delay for timeout testing."""
    global _simulated_delay
    _simulated_delay = delay_seconds


def corpus_search(query: str, top_k: int = 5, timeout_seconds: float = 5.0) -> list[dict]:
    """Search the policy corpus for relevant clauses."""
    start = time.time()

    if _simulated_delay > 0:
        time.sleep(_simulated_delay)

    if "corpus_search" in _simulated_failure:
        raise RuntimeError(_simulated_failure["corpus_search"])

    store = _get_store()
    results = store.search(query, top_k)
    duration = time.time() - start

    if duration > timeout_seconds:
        raise TimeoutError(f"corpus_search timed out after {duration:.2f}s (limit: {timeout_seconds}s)")

    return [
        {
            "text": r.text,
            "source": r.source,
            "page": r.page,
            "clause_id": r.clause_id,
            "similarity_score": getattr(r, "similarity_score", None),
            "retrieval_mode": getattr(r, "retrieval_mode", "lexical"),
            "duration": round(duration, 4),
        }
        for r in results
    ]


def clause_lookup(clause_id: str, timeout_seconds: float = 5.0) -> list[dict]:
    """Look up a specific clause by its identifier (e.g., Code-Excl02)."""
    start = time.time()

    if _simulated_delay > 0:
        time.sleep(_simulated_delay)

    if "clause_lookup" in _simulated_failure:
        raise RuntimeError(_simulated_failure["clause_lookup"])

    store = _get_store()
    results = store.lookup_clause(clause_id)
    duration = time.time() - start

    if duration > timeout_seconds:
        raise TimeoutError(f"clause_lookup timed out after {duration:.2f}s (limit: {timeout_seconds}s)")

    return [
        {
            "text": r.text,
            "source": r.source,
            "page": r.page,
            "clause_id": r.clause_id,
            "similarity_score": getattr(r, "similarity_score", 1.0),
            "retrieval_mode": getattr(r, "retrieval_mode", "exact_lookup"),
        }
        for r in results
    ]


def request_field_lookup(state: dict, field: str) -> str | None:
    """Look up a field from the original pre-auth request."""
    if "request_field_lookup" in _simulated_failure:
        raise RuntimeError(_simulated_failure["request_field_lookup"])

    request = state.get("request")
    if request is None:
        return None
    val = getattr(request, field, None)
    return str(val) if val is not None else None


def execute_tool(
    state: dict,
    tool_name: str,
    query_or_arg: str,
    purpose: str = "",
    retry_number: int = 0,
    timeout_seconds: float = 5.0,
    **kwargs: Any,
) -> dict:
    """
    Centralized tool execution runner that:
    1. Checks and enforces tool call limits
    2. Times tool execution
    3. Handles timeouts and explicit errors
    4. Records the tool call in the state with standardized schema
    """
    run_id = state.get("run_id", "")
    max_tool_calls = state.get("max_tool_calls", 20)
    current_calls = state.get("total_tool_calls", 0)

    # Check bounds
    if current_calls >= max_tool_calls:
        err = f"Maximum tool calls exceeded: {current_calls}/{max_tool_calls}"
        record = {
            "tool": tool_name,
            "query": query_or_arg,
            "purpose": purpose,
            "results": [],
            "result_count": 0,
            "duration_seconds": 0.0,
            "success": False,
            "error": err,
            "retry_number": retry_number,
            "run_id": run_id,
        }
        tool_calls = state.setdefault("tool_calls", [])
        tool_calls.append(record)
        state["total_tool_calls"] = current_calls + 1
        return record

    start = time.time()
    results: list[dict] = []
    success = True
    error_msg: str | None = None

    span_name = f"preauth.tool.{tool_name}"
    span_attrs = {
        "preauth.tool": tool_name,
        "preauth.run_id": run_id,
        "preauth.correlation_id": state.get("correlation_id", run_id),
    }

    with trace_span(span_name, attributes=span_attrs) as span:
        try:
            if tool_name == "corpus_search":
                top_k = kwargs.get("top_k", 5)
                results = corpus_search(query_or_arg, top_k=top_k, timeout_seconds=timeout_seconds)
                if results and "retrieval_mode" in results[0]:
                    span.set_attribute("preauth.retrieval_mode", results[0]["retrieval_mode"])
            elif tool_name == "clause_lookup":
                results = clause_lookup(query_or_arg, timeout_seconds=timeout_seconds)
                if results and "retrieval_mode" in results[0]:
                    span.set_attribute("preauth.retrieval_mode", results[0]["retrieval_mode"])
            elif tool_name == "request_field_lookup":
                val = request_field_lookup(state, query_or_arg)
                results = [{"field": query_or_arg, "value": val}] if val is not None else []
            else:
                raise ValueError(f"Unknown tool: {tool_name}")
        except Exception as exc:
            success = False
            error_msg = str(exc)
            results = []
            record_exception(span, exc)

    duration = time.time() - start

    record = {
        "tool": tool_name,
        "query": query_or_arg,
        "purpose": purpose,
        "results": results,
        "result_count": len(results),
        "duration_seconds": round(duration, 4),
        "success": success,
        "error": error_msg,
        "retry_number": retry_number,
        "run_id": run_id,
    }

    tool_calls = state.setdefault("tool_calls", [])
    tool_calls.append(record)
    state["total_tool_calls"] = state.get("total_tool_calls", 0) + 1

    return record


# Backward compatibility
def retrieve_corpus_clause(query: str, top_k: int = 4, store_path: str = "data/vector_store.json") -> list:
    """Legacy wrapper – returns Chunk objects for backward compatibility."""
    store = _get_store() if store_path == "data/vector_store.json" else VectorStore(store_path)
    return store.retrieve_corpus_clause(query, top_k)
