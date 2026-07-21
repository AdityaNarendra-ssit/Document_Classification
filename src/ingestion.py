"""Read a document and turn it into markdown."""

import io
from pathlib import Path

import markdownify
from docx import Document as DocxDocument
from pypdf import PdfReader


def read_document(source: str) -> str:
    """Read a file path or raw text into a markdown string."""
    # ponytail: accept raw text/markdown inline; caller decides if file exists
    if not Path(source).exists():
        return source

    path = Path(source)
    text = path.read_text(encoding="utf-8", errors="ignore")
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _pdf_to_text(path)
    if suffix == ".docx":
        return _docx_to_markdown(path)
    if suffix in {".html", ".htm"}:
        return markdownify.markdownify(text, heading_style="ATX")
    # .txt, .md, .json, etc. are returned as-is
    return text


def _pdf_to_text(path: Path) -> str:
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n\n".join(parts)


def _docx_to_markdown(path: Path) -> str:
    doc = DocxDocument(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    # ponytail: basic conversion; tables skipped for first version
    return "\n\n".join(paragraphs)


def to_markdown(source: str) -> str:
    """External alias matching the MCP tool name."""
    return read_document(source)


if __name__ == "__main__":
    assert "test" in to_markdown("this is a test").lower()
