"""Deterministic test doubles."""

import hashlib
import math
from collections.abc import Sequence

from bank_assistant.retrieval.lexical import lexical_terms


def whitespace_token_count(text: str) -> int:
    return len(text.split())


class HashingEmbedder:
    """Bag-of-terms vectors via feature hashing: deterministic, instant, no model download.

    Similarity reflects lexical overlap, which is enough to exercise dense retrieval, the
    SQL filters and fusion in tests. It says nothing about the quality of a real model.
    """

    def __init__(self, dimension: int = 256, *, version: str = "1") -> None:
        self.dimension = dimension
        self._version = version

    @property
    def model_id(self) -> str:
        return f"fake:hashing-{self.dimension}-v{self._version}"

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def count_tokens(self, text: str) -> int:
        return whitespace_token_count(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for term in lexical_terms(text):
            digest = hashlib.sha256(term.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]
