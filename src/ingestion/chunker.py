from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class Chunk:
    text: str
    source: str
    page: int | None = None


def _pdf_text(path: Path) -> list[tuple[str, int]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF ingestion requires pypdf; install requirements.txt") from exc
    return [(page.extract_text() or "", number) for number, page in enumerate(PdfReader(str(path)).pages, 1)]


def split_text(text: str, source: str, page: int | None = None, chunk_size: int = 900) -> list[Chunk]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[Chunk] = []
    current = ""
    for paragraph in paragraphs or [text.strip()]:
        candidate = f"{current}\n\n{paragraph}".strip()
        if current and len(candidate) > chunk_size:
            chunks.append(Chunk(current, source, page))
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(Chunk(current, source, page))
    return chunks


def load_documents(corpus_dir: str | Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(Path(corpus_dir).glob("*")):
        if path.suffix.lower() == ".pdf":
            for text, page in _pdf_text(path):
                chunks.extend(split_text(text, path.name, page))
        elif path.suffix.lower() in {".txt", ".md"}:
            chunks.extend(split_text(path.read_text(encoding="utf-8"), path.name))
    return chunks
