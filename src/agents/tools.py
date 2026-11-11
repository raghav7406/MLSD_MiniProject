from src.ingestion.vector_store import VectorStore


def retrieve_corpus_clause(query: str, top_k: int = 4, store_path: str = "data/vector_store.json"):
    return VectorStore(store_path).retrieve_corpus_clause(query, top_k)
