"""Test-only helpers to read the corpus without depending on the ingestion pipeline."""

import re
from pathlib import Path

import pdfplumber

from bank_assistant.ingestion.metadata import SourceDocument, load_markdown

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

_MD_HEADING = re.compile(r"^#{2,4}\s+(\d+(?:\.\d+)*)\.?\s", re.MULTILINE)
_PDF_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+[A-ZÁÉÍÓÚÑ]", re.MULTILINE)


def document_text(doc: SourceDocument) -> str:
    if doc.kind == "markdown":
        _, body = load_markdown(doc.path)
        return body
    with pdfplumber.open(doc.path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def document_sections(doc: SourceDocument) -> set[str]:
    """Numbered section ids of a document, e.g. {"1", "2", "3.1"}."""
    pattern = _MD_HEADING if doc.kind == "markdown" else _PDF_HEADING
    return set(pattern.findall(document_text(doc)))
