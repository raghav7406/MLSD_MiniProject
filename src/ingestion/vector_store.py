from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable

import numpy as np

from .chunker import Chunk
from .embedding import EmbeddingProvider, LocalSemanticEmbeddingProvider


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9-]+", text.lower()))


class VectorStore:
    def __init__(
        self,
        path: str | Path = "data/vector_store.json",
        index_dir: str | Path = "data/semantic_index",
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.path = Path(path)
        self.index_dir = Path(index_dir)
        self.records: list[dict] = []
        self._embeddings: np.ndarray | None = None
        self.embedding_provider = embedding_provider

        # Load lexical/metadata records
        if self.path.exists():
            try:
                self.records = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.records = []

        # Load semantic embedding provider if available and not explicitly passed
        if self.embedding_provider is None and self.index_dir.exists():
            meta_file = self.index_dir / "embedding_meta.json"
            if meta_file.exists():
                try:
                    self.embedding_provider = LocalSemanticEmbeddingProvider.load(self.index_dir)
                except Exception:
                    self.embedding_provider = None

        # Load cached dense embeddings if available
        emb_file = self.index_dir / "embeddings.npy"
        if emb_file.exists():
            try:
                self._embeddings = np.load(emb_file)
            except Exception:
                self._embeddings = None
        elif self.records and "embedding" in self.records[0]:
            try:
                self._embeddings = np.array([r["embedding"] for r in self.records], dtype=np.float32)
            except Exception:
                self._embeddings = None

    def add_chunks(
        self,
        chunks: Iterable[Chunk],
        embeddings: list[list[float]] | np.ndarray | None = None,
    ) -> None:
        chunk_list = list(chunks)
        self.records = [
            {
                "text": c.text,
                "source": c.source,
                "page": c.page,
                "clause_id": c.clause_id,
                "chunk_index": c.chunk_index,
            }
            for c in chunk_list
        ]

        if embeddings is not None:
            if isinstance(embeddings, np.ndarray):
                self._embeddings = embeddings.astype(np.float32)
            else:
                self._embeddings = np.array(embeddings, dtype=np.float32)
        elif self.embedding_provider is not None:
            texts = [c.text for c in chunk_list]
            if texts:
                dense = self.embedding_provider.embed_batch(texts)
                self._embeddings = np.array(dense, dtype=np.float32)
        else:
            self._embeddings = None

    def persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.records, indent=2), encoding="utf-8")

        if self._embeddings is not None:
            self.index_dir.mkdir(parents=True, exist_ok=True)
            np.save(self.index_dir / "embeddings.npy", self._embeddings)

        if self.embedding_provider is not None and hasattr(self.embedding_provider, "save"):
            self.embedding_provider.save(self.index_dir)

    def search_lexical(
        self,
        query: str,
        top_k: int = 5,
        retrieval_mode: str = "lexical",
    ) -> list[Chunk]:
        query_tokens = _tokens(query)
        scored = []
        for record in self.records:
            score = len(query_tokens & _tokens(record["text"]))
            if score > 0:
                scored.append((
                    score,
                    Chunk(
                        record["text"],
                        record["source"],
                        record.get("page"),
                        record.get("clause_id"),
                        record.get("chunk_index", 0),
                        similarity_score=float(score),
                        retrieval_mode=retrieval_mode,
                    ),
                ))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]

    def search_semantic(
        self,
        query: str,
        top_k: int = 5,
        min_similarity: float = 0.01,
    ) -> list[Chunk]:
        """
        Perform cosine similarity search over chunk embeddings.
        Falls back cleanly to lexical search if semantic retrieval is unavailable or produces no hits.
        """
        # Ensure provider and embeddings are ready
        if (
            self.embedding_provider is None
            or self._embeddings is None
            or len(self._embeddings) != len(self.records)
            or len(self.records) == 0
        ):
            return self.search_lexical(query, top_k, retrieval_mode="lexical_fallback")

        try:
            query_vec = np.array(self.embedding_provider.embed_text(query), dtype=np.float32)
            query_norm = np.linalg.norm(query_vec)
            if query_norm == 0.0:
                return self.search_lexical(query, top_k, retrieval_mode="lexical_fallback")
            query_vec = query_vec / query_norm

            # Matrix-vector dot product for cosine similarity
            # Ensure chunk embeddings are normalized
            norms = np.linalg.norm(self._embeddings, axis=1, keepdims=True)
            norms[norms == 0.0] = 1.0
            normed_embeddings = self._embeddings / norms

            scores = np.dot(normed_embeddings, query_vec)

            # Filter and rank
            ranked_indices = np.argsort(scores)[::-1]
            results: list[Chunk] = []

            for idx in ranked_indices:
                score = float(scores[idx])
                if score < min_similarity:
                    break
                rec = self.records[idx]
                results.append(
                    Chunk(
                        rec["text"],
                        rec["source"],
                        rec.get("page"),
                        rec.get("clause_id"),
                        rec.get("chunk_index", 0),
                        similarity_score=round(score, 4),
                        retrieval_mode="semantic",
                    )
                )
                if len(results) >= top_k:
                    break

            if not results:
                # Fall back to lexical if semantic score yielded no matches
                return self.search_lexical(query, top_k, retrieval_mode="lexical_fallback")

            return results
        except Exception:
            return self.search_lexical(query, top_k, retrieval_mode="lexical_fallback")

    def search(self, query: str, top_k: int = 5, min_similarity: float = 0.01) -> list[Chunk]:
        """
        Unified search entry point.
        Uses semantic search if SEMANTIC_RETRIEVAL_ENABLED is true (or 1), otherwise lexical search.
        """
        enabled = os.getenv("SEMANTIC_RETRIEVAL_ENABLED", "false").lower() in {"true", "1", "yes"}
        if enabled:
            return self.search_semantic(query, top_k=top_k, min_similarity=min_similarity)
        return self.search_lexical(query, top_k=top_k, retrieval_mode="lexical")

    def lookup_clause(self, clause_id: str) -> list[Chunk]:
        """Deterministic exact clause lookup by clause_id or textual identifier."""
        results = []
        clause_lower = clause_id.lower()
        for record in self.records:
            rid = (record.get("clause_id") or "").lower()
            text_lower = record["text"].lower()
            if clause_lower in rid or clause_lower in text_lower:
                results.append(
                    Chunk(
                        record["text"],
                        record["source"],
                        record.get("page"),
                        record.get("clause_id"),
                        record.get("chunk_index", 0),
                        similarity_score=1.0,
                        retrieval_mode="exact_lookup",
                    )
                )
        return results

    def retrieve_corpus_clause(self, query: str, top_k: int = 5) -> list[Chunk]:
        return self.search(query, top_k)
