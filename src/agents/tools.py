import time

from src.ingestion.vector_store import VectorStore

_store: VectorStore | None = None


def _get_store(path: str = "data/vector_store.json") -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore(path)
    return _store


def reset_store() -> None:
    """Reset the cached store (useful for testing)."""
    global _store
    _store = None


def corpus_search(query: str, top_k: int = 5) -> list[dict]:
    """Search the policy corpus for relevant clauses."""
    start = time.time()
    store = _get_store()
    results = store.search(query, top_k)
    duration = time.time() - start
    return [
        {
            "text": r.text,
            "source": r.source,
            "page": r.page,
            "clause_id": r.clause_id,
            "duration": round(duration, 4),
        }
        for r in results
    ]


def clause_lookup(clause_id: str) -> list[dict]:
    """Look up a specific clause by its identifier (e.g., Code-Excl02)."""
    store = _get_store()
    results = store.lookup_clause(clause_id)
    return [
        {"text": r.text, "source": r.source, "page": r.page, "clause_id": r.clause_id}
        for r in results
    ]


def request_field_lookup(state: dict, field: str) -> str | None:
    """Look up a field from the original pre-auth request."""
    request = state.get("request")
    if request is None:
        return None
    return str(getattr(request, field, None))


# Backward compatibility
def retrieve_corpus_clause(query: str, top_k: int = 4, store_path: str = "data/vector_store.json") -> list:
    """Legacy wrapper – returns Chunk objects for backward compatibility."""
    store = _get_store() if store_path == "data/vector_store.json" else VectorStore(store_path)
    return store.retrieve_corpus_clause(query, top_k)
