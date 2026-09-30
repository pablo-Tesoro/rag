"""Retrieval: dense (pgvector), lexical (BM25 in SQL) and hybrid (Reciprocal Rank Fusion)."""

from enum import StrEnum


class RetrievalMode(StrEnum):
    DENSE = "dense"
    BM25 = "bm25"
    HYBRID = "hybrid"
