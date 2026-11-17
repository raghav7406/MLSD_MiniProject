"""
Embedding provider interface and local semantic embedding implementations.

Provides:
- EmbeddingProvider: Protocol defining embed_text, embed_batch, dimension, and model_name.
- LocalSemanticEmbeddingProvider: High-performance deterministic TF-IDF + TruncatedSVD / sublinear
  vectorizer producing normalized dense embeddings without external network calls or GPU requirements.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
import joblib


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for embedding providers."""

    @property
    def model_name(self) -> str:
        """Name and version identifier of the embedding model."""
        ...

    @property
    def dimension(self) -> int:
        """Output embedding vector dimensionality."""
        ...

    def embed_text(self, text: str) -> list[float]:
        """Compute an embedding vector for a single text."""
        ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Compute embedding vectors for a batch of texts."""
        ...


class LocalSemanticEmbeddingProvider:
    """
    Deterministic local semantic embedding provider using scikit-learn.
    Uses n-gram TF-IDF with sublinear scaling, English stop-words handling,
    and L2 normalization to produce semantic cosine similarity embeddings.
    """

    def __init__(
        self,
        dimension: int = 512,
        model_name: str = "local-tfidf-semantic-v1",
    ) -> None:
        self._dimension = dimension
        self._model_name = model_name
        self._vectorizer: TfidfVectorizer | None = None
        self._is_fitted = False

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted

    def fit(self, corpus: list[str]) -> None:
        """Fit the vectorizer on the document corpus."""
        if not corpus:
            raise ValueError("Corpus cannot be empty for fitting embedding provider")

        self._vectorizer = TfidfVectorizer(
            max_features=self._dimension,
            ngram_range=(1, 3),
            sublinear_tf=True,
            norm="l2",
            strip_accents="unicode",
            lowercase=True,
            token_pattern=r"(?u)\b\w[\w-]+\b",
        )
        self._vectorizer.fit(corpus)
        self._is_fitted = True

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Compute dense normalized embedding vectors for a list of texts."""
        if not self._is_fitted or self._vectorizer is None:
            raise RuntimeError("LocalSemanticEmbeddingProvider must be fitted before embedding")

        if not texts:
            return []

        sparse_matrix = self._vectorizer.transform(texts)
        dense_array = sparse_matrix.toarray()

        # If sparse matrix has fewer columns than dimension, pad with zeros
        n_rows, n_cols = dense_array.shape
        if n_cols < self._dimension:
            padding = np.zeros((n_rows, self._dimension - n_cols), dtype=np.float32)
            dense_array = np.hstack([dense_array, padding])
        elif n_cols > self._dimension:
            dense_array = dense_array[:, :self._dimension]

        # Ensure L2 normalized
        norms = np.linalg.norm(dense_array, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        dense_array = dense_array / norms

        return dense_array.tolist()

    def embed_text(self, text: str) -> list[float]:
        """Compute dense normalized embedding vector for a single text."""
        return self.embed_batch([text])[0]

    def save(self, directory: str | Path) -> None:
        """Save fitted model and metadata to directory."""
        dir_path = Path(directory)
        dir_path.mkdir(parents=True, exist_ok=True)
        meta = {
            "model_name": self._model_name,
            "dimension": self._dimension,
            "is_fitted": self._is_fitted,
        }
        (dir_path / "embedding_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        if self._vectorizer is not None:
            joblib.dump(self._vectorizer, dir_path / "vectorizer.joblib")

    @classmethod
    def load(cls, directory: str | Path) -> LocalSemanticEmbeddingProvider:
        """Load fitted provider from directory."""
        dir_path = Path(directory)
        meta_file = dir_path / "embedding_meta.json"
        vectorizer_file = dir_path / "vectorizer.joblib"

        if not meta_file.exists():
            raise FileNotFoundError(f"Missing embedding metadata at {meta_file}")

        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        provider = cls(dimension=meta["dimension"], model_name=meta["model_name"])

        if vectorizer_file.exists():
            provider._vectorizer = joblib.load(vectorizer_file)
            provider._is_fitted = meta.get("is_fitted", True)

        return provider


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    a = np.array(v1, dtype=np.float32)
    b = np.array(v2, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))

