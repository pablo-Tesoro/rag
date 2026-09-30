"""Retriever with three selectable modes: dense, bm25 and hybrid (RRF of both).

Security: the permission filter (document groups) and the validity filter (current vs
obsolete) are part of every SQL query, including the final fetch. Nothing the model or the
prompt says can widen them, and a restricted chunk never leaves the database.

BM25 is computed in SQL over the inverted index (`chunk_terms`), with corpus statistics
(N, average length, document frequency) taken over the chunks *visible to this employee*:
scores then do not depend on documents the employee cannot read.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from bank_assistant.db import vector_literal
from bank_assistant.embeddings import Embedder
from bank_assistant.retrieval import RetrievalMode
from bank_assistant.retrieval.fusion import reciprocal_rank_fusion
from bank_assistant.retrieval.lexical import lexical_terms

BM25_K1 = 1.2
BM25_B = 0.75

# Shared by every query: groups overlap + validity. `d` is the documents table.
# Queries are composed with psycopg.sql (never string formatting) and all values are bound
# as parameters.
_ACCESS_FILTER = sql.SQL(
    "d.groups && %(groups)s::text[] AND (%(include_obsolete)s OR d.status = 'vigente')"
)

_DENSE_SQL = sql.SQL("""
    SELECT c.chunk_id, 1 - (c.embedding <=> %(embedding)s::vector) AS score
    FROM chunks c JOIN documents d USING (doc_id)
    WHERE {access_filter}
    ORDER BY c.embedding <=> %(embedding)s::vector, c.chunk_id
    LIMIT %(limit)s
""").format(access_filter=_ACCESS_FILTER)

_BM25_SQL = sql.SQL("""
    WITH visible AS (
        SELECT c.chunk_id, c.term_count
        FROM chunks c JOIN documents d USING (doc_id)
        WHERE {access_filter}
    ),
    stats AS (
        SELECT count(*)::float8 AS n, avg(term_count)::float8 AS avgdl FROM visible
    ),
    df AS (
        SELECT t.term, count(*)::float8 AS df
        FROM chunk_terms t JOIN visible v USING (chunk_id)
        WHERE t.term = ANY(%(terms)s)
        GROUP BY t.term
    )
    SELECT v.chunk_id,
           sum(
               ln(1 + (s.n - df.df + 0.5) / (df.df + 0.5))
               * (t.tf * (%(k1)s + 1))
               / (t.tf + %(k1)s * (1 - %(b)s + %(b)s * v.term_count / s.avgdl))
           ) AS score
    FROM chunk_terms t
    JOIN visible v USING (chunk_id)
    JOIN df USING (term)
    CROSS JOIN stats s
    WHERE t.term = ANY(%(terms)s)
    GROUP BY v.chunk_id
    ORDER BY score DESC, v.chunk_id
    LIMIT %(limit)s
""").format(access_filter=_ACCESS_FILTER)

_FETCH_SQL = sql.SQL("""
    SELECT c.chunk_id, c.doc_id, d.title, d.version, d.status, c.section, c.section_title,
           c.heading_path, c.content
    FROM chunks c JOIN documents d USING (doc_id)
    WHERE c.chunk_id = ANY(%(ids)s) AND {access_filter}
""").format(access_filter=_ACCESS_FILTER)


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    title: str
    version: str
    status: str
    section: str
    section_title: str
    heading_path: str
    content: str
    rank: int
    score: float
    # Rank of the chunk in each underlying list (None if absent); useful to debug fusion.
    component_ranks: dict[str, int | None] = field(default_factory=dict)


class Retriever:
    def __init__(
        self,
        pool: AsyncConnectionPool,
        embedder: Embedder,
        *,
        candidates: int = 20,
        rrf_k: int = 60,
    ) -> None:
        self._pool = pool
        self._embedder = embedder
        self._candidates = candidates
        self._rrf_k = rrf_k

    async def search(
        self,
        query: str,
        *,
        groups: frozenset[str],
        mode: RetrievalMode,
        k: int = 5,
        include_obsolete: bool = False,
    ) -> list[RetrievedChunk]:
        if not groups:
            return []  # no groups, no documents: deny by default
        access = {"groups": sorted(groups), "include_obsolete": include_obsolete}

        if mode is RetrievalMode.DENSE:
            dense = await self._dense(query, access, limit=k)
            ranked = dense
            lists = {"dense": dense}
        elif mode is RetrievalMode.BM25:
            bm25 = await self._bm25(query, access, limit=k)
            ranked = bm25
            lists = {"bm25": bm25}
        else:
            dense, bm25 = await asyncio.gather(
                self._dense(query, access, limit=self._candidates),
                self._bm25(query, access, limit=self._candidates),
            )
            fused = reciprocal_rank_fusion(
                [[chunk_id for chunk_id, _ in dense], [chunk_id for chunk_id, _ in bm25]],
                k=self._rrf_k,
            )
            ranked = fused[:k]
            lists = {"dense": dense, "bm25": bm25}

        return await self._fetch(ranked, lists, access)

    async def _dense(
        self, query: str, access: dict[str, Any], limit: int
    ) -> list[tuple[str, float]]:
        embedding = await asyncio.to_thread(self._embedder.embed_query, query)
        params = {**access, "embedding": vector_literal(embedding), "limit": limit}
        return await self._rows(_DENSE_SQL, params)

    async def _bm25(
        self, query: str, access: dict[str, Any], limit: int
    ) -> list[tuple[str, float]]:
        terms = sorted(set(lexical_terms(query)))
        if not terms:
            return []
        params = {**access, "terms": terms, "limit": limit, "k1": BM25_K1, "b": BM25_B}
        return await self._rows(_BM25_SQL, params)

    async def _rows(self, query: sql.Composed, params: dict[str, Any]) -> list[tuple[str, float]]:
        async with self._pool.connection() as conn:
            cursor = await conn.execute(query, params)
            return [(str(chunk_id), float(score)) for chunk_id, score in await cursor.fetchall()]

    async def _fetch(
        self,
        ranked: list[tuple[str, float]],
        lists: dict[str, list[tuple[str, float]]],
        access: dict[str, Any],
    ) -> list[RetrievedChunk]:
        if not ranked:
            return []
        async with self._pool.connection() as conn:
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(_FETCH_SQL, {**access, "ids": [cid for cid, _ in ranked]})
            rows = {row["chunk_id"]: row for row in await cursor.fetchall()}

        positions = {
            name: {chunk_id: rank for rank, (chunk_id, _) in enumerate(items, start=1)}
            for name, items in lists.items()
        }
        results: list[RetrievedChunk] = []
        for chunk_id, score in ranked:
            row = rows.get(chunk_id)
            if row is None:  # filtered out by the access filter (defence in depth)
                continue
            results.append(
                RetrievedChunk(
                    **row,
                    rank=len(results) + 1,
                    score=score,
                    component_ranks={name: pos.get(chunk_id) for name, pos in positions.items()},
                )
            )
        return results
