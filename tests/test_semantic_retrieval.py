"""
Unit tests for semantic retrieval, embedding provider, and index migration.
"""
from pathlib import Path
import pytest
import numpy as np

from src.ingestion.chunker import Chunk
from src.ingestion.embedding import LocalSemanticEmbeddingProvider, cosine_similarity
from src.ingestion.vector_store import VectorStore


@pytest.fixture
def sample_chunks():
    return [
        Chunk(
            text="Cataract surgery is subject to a specific waiting period of twenty-four (24) months of continuous coverage.",
            source="policy_rules.txt",
            page=4,
            clause_id="Code-Excl02",
            chunk_index=0,
        ),
        Chunk(
            text="Day care treatment procedures do not require 24 hours of hospitalisation when conducted under general anaesthesia.",
            source="daycare_list.txt",
            page=1,
            clause_id="Clause-Daycare",
            chunk_index=1,
        ),
        Chunk(
            text="Pre-existing diseases (PED) are covered only after 36 months of continuous policy coverage.",
            source="exclusions.txt",
            page=7,
            clause_id="Section-PED",
            chunk_index=2,
        ),
    ]


def test_local_semantic_embedding_provider_fit_and_embed(sample_chunks, tmp_path):
    provider = LocalSemanticEmbeddingProvider(dimension=64, model_name="test-tfidf-v1")
    assert not provider.is_fitted

    texts = [c.text for c in sample_chunks]
    provider.fit(texts)
    assert provider.is_fitted

    emb = provider.embed_text("cataract waiting period")
    assert len(emb) == 64
    assert isinstance(emb[0], float)

    # Unit norm check
    norm = np.linalg.norm(emb)
    assert pytest.approx(norm, 0.01) == 1.0

    # Save and reload test
    provider.save(tmp_path / "model")
    loaded = LocalSemanticEmbeddingProvider.load(tmp_path / "model")
    assert loaded.is_fitted
    assert loaded.dimension == 64
    assert loaded.model_name == "test-tfidf-v1"

    emb_reloaded = loaded.embed_text("cataract waiting period")
    assert np.allclose(emb, emb_reloaded)


def test_semantic_retrieval_direct_and_paraphrased(sample_chunks, tmp_path, monkeypatch):
    monkeypatch.setenv("SEMANTIC_RETRIEVAL_ENABLED", "true")
    provider = LocalSemanticEmbeddingProvider(dimension=64)
    provider.fit([c.text for c in sample_chunks])

    store = VectorStore(
        path=tmp_path / "store.json",
        index_dir=tmp_path / "semantic",
        embedding_provider=provider,
    )
    store.add_chunks(sample_chunks)
    store.persist()

    # Direct wording
    direct_res = store.search_semantic("cataract surgery waiting period", top_k=1)
    assert len(direct_res) == 1
    assert direct_res[0].clause_id == "Code-Excl02"
    assert direct_res[0].retrieval_mode == "semantic"
    assert direct_res[0].similarity_score is not None
    assert direct_res[0].similarity_score > 0.0

    # Paraphrased query
    paraphrase_res = store.search_semantic("eye lens operation wait duration months", top_k=1)
    assert len(paraphrase_res) == 1
    assert paraphrase_res[0].clause_id == "Code-Excl02"
    assert paraphrase_res[0].retrieval_mode == "semantic"


def test_semantic_retrieval_metadata_preservation(sample_chunks, tmp_path):
    provider = LocalSemanticEmbeddingProvider(dimension=64)
    provider.fit([c.text for c in sample_chunks])

    store = VectorStore(
        path=tmp_path / "store.json",
        index_dir=tmp_path / "semantic",
        embedding_provider=provider,
    )
    store.add_chunks(sample_chunks)

    results = store.search_semantic("day care treatment anaesthesia", top_k=1)
    assert len(results) == 1
    match = results[0]
    assert match.source == "daycare_list.txt"
    assert match.page == 1
    assert match.clause_id == "Clause-Daycare"
    assert match.chunk_index == 1
    assert match.retrieval_mode == "semantic"


def test_exact_clause_lookup_unaffected(sample_chunks, tmp_path):
    store = VectorStore(path=tmp_path / "store.json")
    store.add_chunks(sample_chunks)

    exact = store.lookup_clause("Code-Excl02")
    assert len(exact) == 1
    assert exact[0].clause_id == "Code-Excl02"
    assert exact[0].retrieval_mode == "exact_lookup"


def test_lexical_fallback_when_semantic_unavailable(sample_chunks, tmp_path, monkeypatch):
    monkeypatch.setenv("SEMANTIC_RETRIEVAL_ENABLED", "true")
    # Vector store with no embedding provider or embeddings
    store = VectorStore(path=tmp_path / "store.json")
    store.add_chunks(sample_chunks)

    # Calling search_semantic must fall back cleanly
    results = store.search_semantic("cataract 24 months", top_k=1)
    assert len(results) == 1
    assert results[0].clause_id == "Code-Excl02"
    assert results[0].retrieval_mode == "lexical_fallback"

