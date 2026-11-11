from dataclasses import dataclass, field
from pathlib import Path
import re


@dataclass(frozen=True)
class Chunk:
    text: str
    source: str
    page: int | None = None
    clause_id: str | None = None
    chunk_index: int = 0


_CLAUSE_PATTERNS = [
    r"Code-Excl\d+",
    r"Section\s+\d+",
    r"Clause\s+\d+",
    r"\d+\.\d+",
]


def _extract_clause_id(text: str) -> str | None:
    for pattern in _CLAUSE_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None


def _pdf_text(path: Path) -> list[tuple[str, int]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF ingestion requires pypdf; install requirements.txt") from exc
    return [(page.extract_text() or "", number) for number, page in enumerate(PdfReader(str(path)).pages, 1)]


def split_text(text: str, source: str, page: int | None = None, chunk_size: int = 600) -> list[Chunk]:
    # Split on section boundaries (== headings ==), double newlines, or numbered sections
    section_pattern = r"(?:\n\s*==\s+.*?==\s*\n|\n\s*\n)"
    parts = re.split(section_pattern, text)
    paragraphs = [part.strip() for part in parts if part and part.strip()]

    chunks: list[Chunk] = []
    current = ""
    idx = 0
    for paragraph in paragraphs or [text.strip()]:
        candidate = f"{current}\n\n{paragraph}".strip()
        if current and len(candidate) > chunk_size:
            clause_id = _extract_clause_id(current)
            chunks.append(Chunk(current, source, page, clause_id, idx))
            idx += 1
            current = paragraph
        else:
            current = candidate
    if current:
        clause_id = _extract_clause_id(current)
        chunks.append(Chunk(current, source, page, clause_id, idx))
    return chunks


def load_documents(corpus_dir: str | Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(Path(corpus_dir).glob("*")):
        if path.suffix.lower() == ".pdf":
            for text, page in _pdf_text(path):
                chunks.extend(split_text(text, path.name, page))
        elif path.suffix.lower() in {".txt", ".md"}:
            raw = path.read_text(encoding="utf-8")
            if raw.strip():
                chunks.extend(split_text(raw, path.name))
    return chunks
