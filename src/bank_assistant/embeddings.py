"""Embedding models behind a small protocol, so ingestion and retrieval do not depend on a
specific library or provider.

The default is a small multilingual model that runs on CPU (`intfloat/multilingual-e5-small`,
384 dimensions, 512-token window). E5 models were trained with "query: " / "passage: "
prefixes and perform worse without them, so the prefixes are part of the configuration.
"""

import math
import re
from collections.abc import Sequence
from typing import Any, Protocol


class Embedder(Protocol):
    @property
    def model_id(self) -> str:
        """Identifies model + preprocessing; part of the index fingerprint."""
        ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...

    def count_tokens(self, text: str) -> int:
        """Tokens the model will see for `text` as a document (prefix included)."""
        ...


_WORDISH = re.compile(r"\w+|[^\w\s]")


def approximate_token_count(text: str) -> int:
    """Heuristic for models whose tokenizer is not available locally (API embeddings):
    subword tokenizers produce roughly 1.3 tokens per Spanish word or symbol."""
    return math.ceil(len(_WORDISH.findall(text)) * 1.3)


class SentenceTransformerEmbedder:
    def __init__(
        self,
        model_name: str,
        *,
        query_prefix: str,
        document_prefix: str,
        batch_size: int = 32,
    ) -> None:
        # Imported lazily: loading torch takes seconds and is only needed here.
        from sentence_transformers import SentenceTransformer

        self._model_name = model_name
        self._query_prefix = query_prefix
        self._document_prefix = document_prefix
        self._batch_size = batch_size
        self._model: Any = SentenceTransformer(model_name, device="cpu")

    @property
    def model_id(self) -> str:
        return (
            f"sentence-transformers:{self._model_name}"
            f"|q={self._query_prefix!r}|d={self._document_prefix!r}"
        )

    @property
    def max_tokens(self) -> int:
        return int(self._model.max_seq_length)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode([self._document_prefix + text for text in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._encode([self._query_prefix + text])[0]

    def count_tokens(self, text: str) -> int:
        encoded = self._model.tokenizer(self._document_prefix + text, add_special_tokens=True)
        return len(encoded["input_ids"])

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts,
            batch_size=self._batch_size,
            normalize_embeddings=True,  # cosine similarity == inner product
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [[float(x) for x in vector] for vector in vectors]
