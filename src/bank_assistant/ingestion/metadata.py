"""Document metadata and corpus discovery.

Markdown documents carry their metadata as YAML front matter. A PDF cannot, so each PDF
has a sidecar `<name>.meta.yaml` with the same fields.

The metadata drives two security-relevant filters that are applied in the database query,
never in the prompt: `groups` (who may read a document) and `status` (current/obsolete).
"""

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

DOCUMENT_ID_PATTERN = r"^NOR-\d{3}$"
FRONT_MATTER_DELIMITER = "---"


class DocumentStatus(StrEnum):
    CURRENT = "vigente"
    OBSOLETE = "obsoleto"


class DocumentMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=DOCUMENT_ID_PATTERN)
    title: str
    version: str = Field(pattern=r"^\d+\.\d+$")
    date: dt.date
    status: DocumentStatus
    groups: frozenset[str] = Field(min_length=1)
    supersedes: str | None = Field(default=None, pattern=DOCUMENT_ID_PATTERN)
    superseded_by: str | None = Field(default=None, pattern=DOCUMENT_ID_PATTERN)

    @model_validator(mode="after")
    def _status_matches_lineage(self) -> Self:
        if self.status is DocumentStatus.OBSOLETE and self.superseded_by is None:
            raise ValueError(f"{self.id}: an obsolete document must name its superseded_by")
        if self.status is DocumentStatus.CURRENT and self.superseded_by is not None:
            raise ValueError(f"{self.id}: a current document cannot be superseded")
        return self


@dataclass(frozen=True)
class SourceDocument:
    """A corpus file plus its metadata, before any parsing of its content."""

    path: Path
    kind: Literal["markdown", "pdf"]
    metadata: DocumentMetadata


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Split a Markdown file into (front-matter mapping, body)."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != FRONT_MATTER_DELIMITER:
        raise ValueError("Missing YAML front matter: the file must start with '---'")
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == FRONT_MATTER_DELIMITER:
            header = yaml.safe_load("".join(lines[1:index])) or {}
            if not isinstance(header, dict):
                raise ValueError("Front matter must be a YAML mapping")
            return header, "".join(lines[index + 1 :])
    raise ValueError("Unterminated YAML front matter: closing '---' not found")


def load_markdown(path: Path) -> tuple[DocumentMetadata, str]:
    header, body = split_front_matter(path.read_text(encoding="utf-8"))
    return DocumentMetadata.model_validate(header), body


def pdf_sidecar_path(pdf_path: Path) -> Path:
    return pdf_path.with_suffix(".meta.yaml")


def load_pdf_metadata(pdf_path: Path) -> DocumentMetadata:
    sidecar = pdf_sidecar_path(pdf_path)
    raw = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    return DocumentMetadata.model_validate(raw)


def discover_corpus(corpus_dir: Path) -> list[SourceDocument]:
    """List every corpus document with its validated metadata, sorted by document id."""
    documents: list[SourceDocument] = []
    for path in sorted(corpus_dir.iterdir()):
        if path.suffix == ".md":
            metadata, _ = load_markdown(path)
            documents.append(SourceDocument(path=path, kind="markdown", metadata=metadata))
        elif path.suffix == ".pdf":
            metadata = load_pdf_metadata(path)
            documents.append(SourceDocument(path=path, kind="pdf", metadata=metadata))
    return sorted(documents, key=lambda doc: doc.metadata.id)
