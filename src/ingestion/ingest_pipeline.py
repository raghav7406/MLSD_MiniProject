from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from .chunker import load_documents
from .embedding import LocalSemanticEmbeddingProvider
from .vector_store import VectorStore


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _corpus_hashes(corpus_dir: Path) -> dict[str, str]:
    hashes = {}
    for path in sorted(corpus_dir.glob("*")):
        if path.is_file() and path.suffix.lower() in {".txt", ".md", ".pdf"}:
            hashes[path.name] = _file_hash(path)
    return hashes


def ingest(
    corpus_dir: str | Path = "data/corpus",
    store_path: str | Path = "data/vector_store.json",
    manifest_path: str | Path = "data/index_manifest.json",
    index_dir: str | Path = "data/semantic_index",
    force: bool = False,
) -> int:
    corpus_dir = Path(corpus_dir)
    manifest_path = Path(manifest_path)
    index_dir = Path(index_dir)
    store_path = Path(store_path)

    current_hashes = _corpus_hashes(corpus_dir)

    # Idempotency check: skip if nothing changed
    if not force and manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("corpus_versions") == current_hashes and (index_dir / "embeddings.npy").exists():
                print("Corpus unchanged and semantic index exists; skipping rebuild. Use --force to override.")
                return manifest.get("chunk_count", 0)
        except Exception:
            pass

    start = time.time()
    chunks = load_documents(corpus_dir)
    texts = [c.text for c in chunks]

    # Initialize and fit semantic embedding provider
    provider = LocalSemanticEmbeddingProvider(dimension=512, model_name="local-tfidf-semantic-v1")
    if texts:
        provider.fit(texts)

    # Create vector store with provider
    store = VectorStore(
        path=store_path,
        index_dir=index_dir,
        embedding_provider=provider,
    )
    store.add_chunks(chunks)
    store.persist()
    duration = time.time() - start

    manifest = {
        "build_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "corpus_versions": current_hashes,
        "embedding_model": provider.model_name,
        "vector_dimension": provider.dimension,
        "chunk_count": len(chunks),
        "processing_duration_seconds": round(duration, 3),
        "throughput_chunks_per_second": round(len(chunks) / max(duration, 0.001), 1),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return len(chunks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest policy documents and build semantic index")
    parser.add_argument("--corpus", default="data/corpus")
    parser.add_argument("--store", default="data/vector_store.json")
    parser.add_argument("--index-dir", default="data/semantic_index")
    parser.add_argument("--manifest", default="data/index_manifest.json")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    count = ingest(
        corpus_dir=args.corpus,
        store_path=args.store,
        index_dir=args.index_dir,
        manifest_path=args.manifest,
        force=args.force,
    )
    print(f"Ingested {count} chunks with semantic embeddings")
