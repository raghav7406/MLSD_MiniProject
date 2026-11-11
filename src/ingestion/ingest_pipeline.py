import argparse
from pathlib import Path

from .chunker import load_documents
from .vector_store import VectorStore


def ingest(corpus_dir: str | Path = "data/corpus", store_path: str | Path = "data/vector_store.json") -> int:
    chunks = load_documents(corpus_dir)
    store = VectorStore(store_path)
    store.add_chunks(chunks)
    store.persist()
    return len(chunks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest policy documents")
    parser.add_argument("--corpus", default="data/corpus")
    parser.add_argument("--store", default="data/vector_store.json")
    args = parser.parse_args()
    print(f"Ingested {ingest(args.corpus, args.store)} chunks")
