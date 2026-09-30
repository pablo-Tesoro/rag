"""Retrieval metrics over `(doc_id, section)` labels.

A retrieved chunk matches a label when it belongs to the labelled document and to the
labelled section or one of its subsections ("3" matches chunks of "3" and "3.1").

- recall@k: fraction of the labelled sections found among the top-k chunks. With several
  labels (multi-hop questions) it rewards finding all the pieces, not just one.
- reciprocal rank: 1 / position of the first chunk that matches any label (0 if none).
  Its mean over cases is MRR.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from evals.schema import SectionRef


class ChunkLike(Protocol):
    @property
    def doc_id(self) -> str: ...

    @property
    def section(self) -> str: ...


def matches(chunk: ChunkLike, label: SectionRef) -> bool:
    return chunk.doc_id == label.doc_id and (
        chunk.section == label.section or chunk.section.startswith(label.section + ".")
    )


def recall_at_k(ranked: Sequence[ChunkLike], labels: Sequence[SectionRef], k: int) -> float:
    if not labels:
        raise ValueError("recall is undefined without relevant labels")
    top = ranked[:k]
    found = sum(1 for label in labels if any(matches(chunk, label) for chunk in top))
    return found / len(labels)


def reciprocal_rank(ranked: Sequence[ChunkLike], labels: Sequence[SectionRef]) -> float:
    for position, chunk in enumerate(ranked, start=1):
        if any(matches(chunk, label) for label in labels):
            return 1.0 / position
    return 0.0


@dataclass(frozen=True)
class RetrievalScore:
    recall: float
    reciprocal_rank: float


def score_ranking(
    ranked: Sequence[ChunkLike], labels: Sequence[SectionRef], k: int
) -> RetrievalScore:
    return RetrievalScore(
        recall=recall_at_k(ranked, labels, k), reciprocal_rank=reciprocal_rank(ranked, labels)
    )
