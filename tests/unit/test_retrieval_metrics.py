from dataclasses import dataclass

import pytest

from evals.metrics.retrieval import matches, recall_at_k, reciprocal_rank
from evals.retrieval_eval import RetrievalGate
from evals.schema import SectionRef


@dataclass(frozen=True)
class FakeChunk:
    doc_id: str
    section: str


def ref(doc_id: str, section: str) -> SectionRef:
    return SectionRef(doc_id=doc_id, section=section)


def test_a_label_matches_its_section_and_subsections_only() -> None:
    label = ref("NOR-001", "3")

    assert matches(FakeChunk("NOR-001", "3"), label)
    assert matches(FakeChunk("NOR-001", "3.1"), label)
    assert not matches(FakeChunk("NOR-001", "31"), label)  # prefix of the number, not a child
    assert not matches(FakeChunk("NOR-002", "3"), label)


def test_recall_counts_labels_found_in_the_top_k() -> None:
    ranked = [FakeChunk("NOR-006", "3"), FakeChunk("NOR-001", "1"), FakeChunk("NOR-007", "2")]
    labels = [ref("NOR-006", "3"), ref("NOR-007", "2")]

    assert recall_at_k(ranked, labels, k=3) == 1.0
    assert recall_at_k(ranked, labels, k=2) == 0.5


def test_several_chunks_of_the_same_section_count_once() -> None:
    ranked = [FakeChunk("NOR-009", "5"), FakeChunk("NOR-009", "5")]

    assert recall_at_k(ranked, [ref("NOR-009", "5"), ref("NOR-009", "3")], k=5) == 0.5


def test_reciprocal_rank_uses_the_first_relevant_position() -> None:
    ranked = [FakeChunk("NOR-001", "1"), FakeChunk("NOR-002", "2"), FakeChunk("NOR-003", "2")]

    assert reciprocal_rank(ranked, [ref("NOR-003", "2"), ref("NOR-002", "2")]) == 0.5
    assert reciprocal_rank(ranked, [ref("NOR-010", "1")]) == 0.0


def test_recall_needs_labels() -> None:
    with pytest.raises(ValueError):
        recall_at_k([], [], k=5)


def test_retrieval_gate_fails_when_a_whole_case_is_lost() -> None:
    gate = RetrievalGate()

    assert gate.evaluate({"recall": 12.5 / 13, "mrr": 0.91}) == []  # the phase 2 baseline
    assert gate.evaluate({"recall": 12 / 13, "mrr": 0.87}) == []  # half a case, one position
    assert gate.evaluate({"recall": 11.5 / 13, "mrr": 0.91}) == ["recall 0.885 < 0.90"]
    assert gate.evaluate({"recall": 1.0, "mrr": 0.83}) == ["MRR 0.830 < 0.85"]
