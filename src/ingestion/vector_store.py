import json
import re
from pathlib import Path
from typing import Iterable

from .chunker import Chunk


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9-]+", text.lower()))


class VectorStore:
    def __init__(self, path: str | Path = "data/vector_store.json") -> None:
        self.path = Path(path)
        self.records: list[dict] = []
        if self.path.exists():
            self.records = json.loads(self.path.read_text(encoding="utf-8"))

    def add_chunks(self, chunks: Iterable[Chunk]) -> None:
        self.records = [{"text": c.text, "source": c.source, "page": c.page} for c in chunks]

    def persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.records, indent=2), encoding="utf-8")

    def search(self, query: str, top_k: int = 4) -> list[Chunk]:
        query_tokens = _tokens(query)
        scored = []
        for record in self.records:
            score = len(query_tokens & _tokens(record["text"]))
            if score:
                scored.append((score, Chunk(record["text"], record["source"], record.get("page"))))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]

    def retrieve_corpus_clause(self, query: str, top_k: int = 4) -> list[Chunk]:
        return self.search(query, top_k)
