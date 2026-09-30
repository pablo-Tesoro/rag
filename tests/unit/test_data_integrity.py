"""Integrity checks for the fictitious data: they catch broken metadata, dangling
cross-references and inconsistent operations before anything is ingested."""

import re

import pytest

from bank_assistant.core_banking.models import OPERATION_ID_PATTERN, load_offices, load_operations
from bank_assistant.identity import EmployeeDirectory
from bank_assistant.ingestion.metadata import DocumentStatus, SourceDocument, discover_corpus
from scripts import generate_operations
from tests.helpers import DATA_DIR, document_sections, document_text

CURATED_OPERATION_IDS = {
    "OP-104233",
    "OP-582214",
    "OP-731904",
    "OP-208871",
    "OP-639015",
    "OP-310552",
    "OP-477120",
}


@pytest.fixture(scope="module")
def corpus() -> list[SourceDocument]:
    return discover_corpus(DATA_DIR / "corpus")


@pytest.fixture(scope="module")
def employees() -> EmployeeDirectory:
    return EmployeeDirectory.from_file(DATA_DIR / "employees.json")


def test_corpus_has_expected_size_and_formats(corpus: list[SourceDocument]) -> None:
    assert len(corpus) == 13
    assert sum(doc.kind == "pdf" for doc in corpus) == 2
    assert len({doc.metadata.id for doc in corpus}) == len(corpus)


def test_every_document_is_marked_as_fictitious(corpus: list[SourceDocument]) -> None:
    for doc in corpus:
        assert "Documento ficticio de Banco Olvessa" in document_text(doc), doc.metadata.id


def test_every_document_is_organised_in_numbered_sections(corpus: list[SourceDocument]) -> None:
    for doc in corpus:
        sections = document_sections(doc)
        assert "1" in sections, f"{doc.metadata.id} has no section 1: {sections}"


def test_obsolete_and_current_versions_point_to_each_other(corpus: list[SourceDocument]) -> None:
    by_id = {doc.metadata.id: doc.metadata for doc in corpus}
    obsolete = [meta for meta in by_id.values() if meta.status is DocumentStatus.OBSOLETE]
    assert obsolete, "the corpus needs at least one obsolete policy"
    for meta in obsolete:
        assert meta.superseded_by is not None
        replacement = by_id[meta.superseded_by]
        assert replacement.status is DocumentStatus.CURRENT
        assert replacement.supersedes == meta.id


def test_restricted_documents_exist_and_are_readable_by_someone(
    corpus: list[SourceDocument], employees: EmployeeDirectory
) -> None:
    all_groups = set().union(*(employee.groups for employee in employees))
    restricted = [doc for doc in corpus if "todos" not in doc.metadata.groups]
    assert len(restricted) >= 2
    for doc in corpus:
        assert doc.metadata.groups & all_groups, f"nobody can read {doc.metadata.id}"


def test_cross_references_point_to_existing_documents(corpus: list[SourceDocument]) -> None:
    ids = {doc.metadata.id for doc in corpus}
    for doc in corpus:
        referenced = set(re.findall(r"NOR-\d{3}", document_text(doc)))
        assert referenced <= ids, f"{doc.metadata.id} references unknown {referenced - ids}"


def test_operations_are_consistent() -> None:
    operations = load_operations(DATA_DIR / "core_banking" / "operations.json")
    office_ids = {office.id for office in load_offices(DATA_DIR / "core_banking" / "offices.json")}
    ids = [op.id for op in operations]

    assert len(operations) == 50
    assert len(set(ids)) == len(ids)
    assert all(re.fullmatch(OPERATION_ID_PATTERN, op_id) for op_id in ids)
    assert {op.office_id for op in operations} <= office_ids
    assert set(ids) >= CURATED_OPERATION_IDS
    assert "OP-999999" not in ids  # reserved as "does not exist" for evals


def test_employees_belong_to_existing_offices(employees: EmployeeDirectory) -> None:
    office_ids = {office.id for office in load_offices(DATA_DIR / "core_banking" / "offices.json")}

    assert len(employees) == 3
    assert {employee.office_id for employee in employees} <= office_ids
    assert all("todos" in employee.groups for employee in employees)


def test_operations_file_matches_its_generator() -> None:
    # The operations file must be exactly what the generator produces (no hand edits).
    actual = load_operations(DATA_DIR / "core_banking" / "operations.json")
    assert actual == generate_operations.generate()
