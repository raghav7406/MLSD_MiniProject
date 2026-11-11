import argparse
import hashlib
import json
import time
from pathlib import Path

from .chunker import load_documents
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
    force: bool = False,
) -> int:
    corpus_dir = Path(corpus_dir)
    manifest_path = Path(manifest_path)

    current_hashes = _corpus_hashes(corpus_dir)

    # Idempotency: skip if nothing changed
    if not force and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("corpus_versions") == current_hashes:
            print("Corpus unchanged; skipping rebuild. Use --force to override.")
            return manifest.get("chunk_count", 0)

    start = time.time()
    chunks = load_documents(corpus_dir)
    store = VectorStore(store_path)
    store.add_chunks(chunks)
    store.persist()
    duration = time.time() - start

    manifest = {
        "build_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "corpus_versions": current_hashes,
        "embedding_version": "token-overlap-v2",
        "chunk_count": len(chunks),
        "processing_duration_seconds": round(duration, 3),
        "throughput_chunks_per_second": round(len(chunks) / max(duration, 0.001), 1),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return len(chunks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest policy documents")
    parser.add_argument("--corpus", default="data/corpus")
    parser.add_argument("--store", default="data/vector_store.json")
    parser.add_argument("--manifest", default="data/index_manifest.json")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(f"Ingested {ingest(args.corpus, args.store, args.manifest, args.force)} chunks")
