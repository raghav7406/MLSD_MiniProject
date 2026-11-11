"""Tests for the ingestion pipeline and vector store."""
import json
from pathlib import Path

from src.ingestion.chunker import Chunk, split_text, load_documents, _extract_clause_id
from src.ingestion.vector_store import VectorStore
from src.ingestion.ingest_pipeline import ingest


class TestChunker:
    def test_split_text_produces_chunks(self):
        text = "Section 1: Coverage\n\nCataract surgery is covered.\n\nSection 2: Exclusions\n\nCosmetic surgery is excluded."
        chunks = split_text(text, "test.txt")
        assert len(chunks) >= 1
        assert all(isinstance(c, Chunk) for c in chunks)

    def test_clause_id_extraction(self):
        assert _extract_clause_id("Code-Excl02 applies here") == "Code-Excl02"
        assert _extract_clause_id("Section 5 covers waiting periods") == "Section 5"
        assert _extract_clause_id("No clause here") is None

    def test_chunk_has_source(self):
        chunks = split_text("Test content", "policy.txt")
        assert chunks[0].source == "policy.txt"


class TestVectorStore:
    def test_search_returns_relevant_results(self, tmp_path):
        store = VectorStore(tmp_path / "test_store.json")
        chunks = [
            Chunk("Cataract surgery is covered after 24 months", "policy.txt", clause_id="Code-Excl02"),
            Chunk("Emergency hospitalisation is covered", "policy.txt"),
            Chunk("Dental surgery for cosmetic reasons is excluded", "policy.txt"),
        ]
        store.add_chunks(chunks)
        store.persist()

        results = store.search("cataract surgery coverage", top_k=2)
        assert len(results) > 0
        assert "cataract" in results[0].text.lower()

    def test_clause_lookup(self, tmp_path):
        store = VectorStore(tmp_path / "test_store.json")
        chunks = [
            Chunk("Code-Excl02: 24-month waiting period for cataract", "policy.txt", clause_id="Code-Excl02"),
            Chunk("General coverage applies", "policy.txt"),
        ]
        store.add_chunks(chunks)
        store.persist()

        results = store.lookup_clause("Code-Excl02")
        assert len(results) >= 1
        assert "Code-Excl02" in results[0].text

    def test_persist_and_reload(self, tmp_path):
        path = tmp_path / "store.json"
        store1 = VectorStore(path)
        store1.add_chunks([Chunk("Test chunk", "test.txt")])
        store1.persist()

        store2 = VectorStore(path)
        assert len(store2.records) == 1


class TestIngestPipeline:
    def test_ingest_creates_store(self, tmp_path):
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "test_policy.txt").write_text("Test policy content for ingestion.")

        store_path = tmp_path / "store.json"
        manifest_path = tmp_path / "manifest.json"

        count = ingest(str(corpus_dir), str(store_path), str(manifest_path), force=True)
        assert count >= 1
        assert store_path.exists()
        assert manifest_path.exists()

        manifest = json.loads(manifest_path.read_text())
        assert "chunk_count" in manifest
        assert "corpus_versions" in manifest

    def test_ingest_idempotent(self, tmp_path):
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "test.txt").write_text("Test content.")
        store_path = tmp_path / "store.json"
        manifest_path = tmp_path / "manifest.json"

        count1 = ingest(str(corpus_dir), str(store_path), str(manifest_path), force=True)
        count2 = ingest(str(corpus_dir), str(store_path), str(manifest_path), force=False)
        assert count1 == count2

