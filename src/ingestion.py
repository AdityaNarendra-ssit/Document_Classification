"""Read a document and turn it into markdown.

Supports common office formats (PDF, DOCX, HTML) and plain text. The main
entry point is :func:`read_document`, with :func:`to_markdown` provided as a
convenience alias matching the MCP tool name.
"""

import io
from pathlib import Path

import markdownify
from docx import Document as DocxDocument
from loguru import logger
from pypdf import PdfReader


def read_document(source: str) -> str:
    """Read a file path or raw text into a markdown string.

    If ``source`` points to an existing file, the file is opened and converted
    according to its extension. If the path does not exist, ``source`` is
    returned unchanged (treating it as raw text/markdown).

    Args:
        source: A filesystem path to a document, or a raw text/markdown string.

    Returns:
        The document content as markdown or plain text.
    """
    logger.debug("read_document called with source length {}", len(source))

    if not Path(source).exists():
        logger.warning(
            "Path '{}' not found; treating input as raw text/markdown ({} characters)",
            source,
            len(source),
        )
        return source

    path = Path(source)
    logger.info("Reading document from {}", path)

    text = path.read_text(encoding="utf-8", errors="ignore")
    suffix = path.suffix.lower()
    logger.debug("Detected file extension: {}", suffix)

    if suffix == ".pdf":
        return _pdf_to_text(path)
    if suffix == ".docx":
        return _docx_to_markdown(path)
    if suffix in {".html", ".htm"}:
        logger.info("Converting HTML to markdown using markdownify")
        return markdownify.markdownify(text, heading_style="ATX")

    # .txt, .md, .json, etc. are returned as-is.
    logger.info("Returning plain text content for {} extension", suffix)
    return text


def _pdf_to_text(path: Path) -> str:
    """Extract text from a PDF file.

    Args:
        path: Path to a ``.pdf`` file.

    Returns:
        Concatenated text from all pages, separated by blank lines.
    """
    logger.info("Extracting text from PDF: {}", path)
    reader = PdfReader(str(path))
    parts = []
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        parts.append(page_text)
        logger.debug("Extracted {} characters from page {}", len(page_text), page_number)

    result = "\n\n".join(parts)
    logger.info("PDF extraction complete: {} pages, {} total characters", len(reader.pages), len(result))
    return result


def _docx_to_markdown(path: Path) -> str:
    """Convert a DOCX file to a basic markdown string.

    Paragraphs are joined with blank lines. Tables are intentionally skipped in
    this first version.

    Args:
        path: Path to a ``.docx`` file.

    Returns:
        Markdown-ish text built from the document paragraphs.
    """
    logger.info("Converting DOCX to markdown: {}", path)
    doc = DocxDocument(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    result = "\n\n".join(paragraphs)
    logger.info(
        "DOCX conversion complete: {} paragraphs, {} total characters",
        len(paragraphs),
        len(result),
    )
    return result


def to_markdown(source: str) -> str:
    """External alias matching the MCP tool name.

    Delegates to :func:`read_document`.

    Args:
        source: A filesystem path to a document, or a raw text/markdown string.

    Returns:
        The document content as markdown or plain text.
    """
    logger.debug("to_markdown called")
    return read_document(source)


if __name__ == "__main__":
    sample_text = to_markdown("this is a test")
    logger.info("Self-test result: {}", sample_text)
    assert "test" in sample_text.lower()
