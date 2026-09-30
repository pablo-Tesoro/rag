"""Consistency checks between the eval dataset and the fictitious data.

A mislabelled case silently corrupts every metric, so labels are validated against the
corpus, the employees and the core-banking operations.
"""

from collections import Counter

import pytest

from bank_assistant.core_banking.models import Operation, load_operations
from bank_assistant.identity import EmployeeDirectory
from bank_assistant.ingestion.metadata import DocumentStatus, SourceDocument, discover_corpus
from evals.schema import Category, EvalCase, load_dataset
from tests.helpers import DATA_DIR, document_sections, document_text

DATASET = DATA_DIR.parent / "evals" / "dataset.jsonl"
CRITICAL_CATEGORIES = {Category.PERMISSIONS, Category.INJECTION, Category.HUMAN_APPROVAL}
INCIDENT_CATEGORIES = {
    "cargo_duplicado",
    "importe_incorrecto",
    "abono_no_recibido",
    "operacion_no_reconocida",
    "otro",
}
NONEXISTENT_OPERATION = "OP-999999"


@pytest.fixture(scope="module")
def cases() -> list[EvalCase]:
    return load_dataset(DATASET)


@pytest.fixture(scope="module")
def docs() -> dict[str, SourceDocument]:
    return {doc.metadata.id: doc for doc in discover_corpus(DATA_DIR / "corpus")}


@pytest.fixture(scope="module")
def employees() -> EmployeeDirectory:
    return EmployeeDirectory.from_file(DATA_DIR / "employees.json")


@pytest.fixture(scope="module")
def operations() -> dict[str, Operation]:
    return {op.id: op for op in load_operations(DATA_DIR / "core_banking" / "operations.json")}


def test_dataset_size_splits_and_coverage(cases: list[EvalCase]) -> None:
    assert len(cases) == 30
    assert len({case.id for case in cases}) == 30
    assert Counter(case.split for case in cases) == {"dev": 20, "test": 10}
    for split in ("dev", "test"):
        covered = {case.category for case in cases if case.split == split}
        assert covered == set(Category), f"{split} misses {set(Category) - covered}"


def test_critical_flag_matches_category(cases: list[EvalCase]) -> None:
    for case in cases:
        assert case.critical == (case.category in CRITICAL_CATEGORIES), case.id


def test_relevant_sections_exist_and_are_readable_by_the_employee(
    cases: list[EvalCase], docs: dict[str, SourceDocument], employees: EmployeeDirectory
) -> None:
    for case in cases:
        employee = employees.get(case.employee_id)
        assert employee is not None, case.id
        wants_obsolete = any(
            call.args.get("incluir_obsoletos") is True for call in case.expected_tool_calls
        )
        for ref in case.relevant:
            doc = docs[ref.doc_id]
            assert ref.section in document_sections(doc), f"{case.id}: {ref} does not exist"
            assert doc.metadata.groups & employee.groups, f"{case.id}: {ref.doc_id} not readable"
            if doc.metadata.status is DocumentStatus.OBSOLETE:
                assert wants_obsolete, f"{case.id}: cites obsolete {ref.doc_id} without asking"


def test_forbidden_documents_are_really_forbidden_for_permission_cases(
    cases: list[EvalCase], docs: dict[str, SourceDocument], employees: EmployeeDirectory
) -> None:
    for case in cases:
        employee = employees.get(case.employee_id)
        assert employee is not None
        for doc_id in case.forbidden.doc_ids:
            assert doc_id in docs, f"{case.id}: unknown forbidden doc {doc_id}"
            if case.category is Category.PERMISSIONS:
                readable = docs[doc_id].metadata.groups & employee.groups
                assert not readable, f"{case.id}: {doc_id} is readable by {employee.id}"


def test_forbidden_strings_exist_in_the_data(
    cases: list[EvalCase], docs: dict[str, SourceDocument], operations: dict[str, Operation]
) -> None:
    # Otherwise the leak check would be vacuous: it would pass whatever the agent does.
    haystack = "\n".join(document_text(doc) for doc in docs.values())
    haystack += "\n".join(op.model_dump_json() for op in operations.values())
    for case in cases:
        for needle in case.forbidden.strings:
            variants = {needle, needle.replace(".", "")}
            assert any(variant in haystack for variant in variants), f"{case.id}: {needle!r}"


def test_expected_tool_calls_reference_real_operations(
    cases: list[EvalCase], operations: dict[str, Operation], employees: EmployeeDirectory
) -> None:
    for case in cases:
        employee = employees.get(case.employee_id)
        assert employee is not None
        for call in case.expected_tool_calls:
            op_id = call.args.get("id_operacion")
            if call.name == "abrir_incidencia":
                assert call.args.get("categoria") in INCIDENT_CATEGORIES, case.id
            if op_id is None or op_id == NONEXISTENT_OPERATION:
                continue
            same_office = operations[op_id].office_id == employee.office_id
            expected_same_office = case.category is not Category.PERMISSIONS
            assert same_office == expected_same_office, f"{case.id}: office mismatch for {op_id}"
