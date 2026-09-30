from pathlib import Path

import pytest
from pydantic import ValidationError

from bank_assistant.ingestion.metadata import (
    DocumentMetadata,
    DocumentStatus,
    load_markdown,
    split_front_matter,
)

VALID_HEADER = {
    "id": "NOR-999",
    "title": "Documento de prueba",
    "version": "1.0",
    "date": "2025-01-01",
    "status": "vigente",
    "groups": ["todos"],
}


def test_split_front_matter_returns_header_and_body() -> None:
    header, body = split_front_matter("---\nid: NOR-001\n---\n# Título\n")

    assert header == {"id": "NOR-001"}
    assert body == "# Título\n"


@pytest.mark.parametrize("text", ["# No header\n", "---\nid: NOR-001\n# never closed\n"])
def test_split_front_matter_rejects_missing_or_unterminated_header(text: str) -> None:
    with pytest.raises(ValueError, match="front matter"):
        split_front_matter(text)


def test_load_markdown_validates_metadata(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(
        "---\nid: NOR-999\ntitle: Prueba\nversion: '1.0'\ndate: 2025-01-01\n"
        "status: vigente\ngroups: [todos]\n---\n# Prueba\n",
        encoding="utf-8",
    )

    metadata, body = load_markdown(doc)

    assert metadata.id == "NOR-999"
    assert metadata.status is DocumentStatus.CURRENT
    assert body.startswith("# Prueba")


def test_obsolete_document_must_name_its_replacement() -> None:
    with pytest.raises(ValidationError, match="superseded_by"):
        DocumentMetadata.model_validate({**VALID_HEADER, "status": "obsoleto"})


def test_current_document_cannot_be_superseded() -> None:
    with pytest.raises(ValidationError, match="cannot be superseded"):
        DocumentMetadata.model_validate({**VALID_HEADER, "superseded_by": "NOR-001"})


def test_unquoted_yaml_version_is_rejected_instead_of_silently_coerced() -> None:
    # YAML reads `version: 2.0` as a float; we want the author to quote it.
    with pytest.raises(ValidationError):
        DocumentMetadata.model_validate({**VALID_HEADER, "version": 2.0})


def test_document_needs_at_least_one_group() -> None:
    with pytest.raises(ValidationError):
        DocumentMetadata.model_validate({**VALID_HEADER, "groups": []})
