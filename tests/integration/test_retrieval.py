import math
from collections import Counter

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

from bank_assistant.ingestion.chunking import ChunkConfig
from bank_assistant.ingestion.pipeline import ingest_corpus
from bank_assistant.retrieval import RetrievalMode
from bank_assistant.retrieval.lexical import lexical_terms
from bank_assistant.retrieval.retriever import BM25_B, BM25_K1, Retriever
from tests.fakes import HashingEmbedder
from tests.helpers import DATA_DIR

EVERYONE = frozenset({"todos"})
RISK = frozenset({"todos", "riesgos"})
ALL_GROUPS = frozenset({"todos", "riesgos", "cumplimiento"})
RESTRICTED = {"NOR-011", "NOR-012", "NOR-013"}


@pytest.fixture(scope="module")
async def retriever(schema_conninfo: str, pool: AsyncConnectionPool) -> Retriever:
    async with await psycopg.AsyncConnection.connect(schema_conninfo) as conn:
        await ingest_corpus(
            conn,
            DATA_DIR / "corpus",
            HashingEmbedder(),
            ChunkConfig(max_tokens=200, overlap_tokens=30),
        )
    return Retriever(pool, HashingEmbedder(), candidates=20, rrf_k=60)


@pytest.mark.parametrize("mode", list(RetrievalMode))
async def test_restricted_documents_never_reach_employees_outside_the_group(
    retriever: Retriever, mode: RetrievalMode
) -> None:
    queries = [
        "puntuación mínima de scoring OLV-SCORE-3 admisión automática",
        "matriz de delegación de facultades de riesgo comité",
        "formulario COS-7 canal ALERTA-OLV-77 operaciones sospechosas",
    ]
    for query in queries:
        results = await retriever.search(query, groups=EVERYONE, mode=mode, k=20)
        assert results, "the employee should still get public chunks"
        assert not {r.doc_id for r in results} & RESTRICTED


@pytest.mark.parametrize("mode", list(RetrievalMode))
async def test_group_members_do_get_their_restricted_documents(
    retriever: Retriever, mode: RetrievalMode
) -> None:
    results = await retriever.search(
        "puntuación mínima de scoring OLV-SCORE-3", groups=RISK, mode=mode, k=5
    )
    doc_ids = {r.doc_id for r in results}

    assert "NOR-011" in doc_ids
    assert "NOR-013" not in doc_ids  # riesgos does not include cumplimiento


@pytest.mark.parametrize("mode", list(RetrievalMode))
async def test_obsolete_documents_only_when_explicitly_requested(
    retriever: Retriever, mode: RetrievalMode
) -> None:
    query = "límite diario transferencia inmediata oficina"

    current_only = await retriever.search(query, groups=EVERYONE, mode=mode, k=20)
    with_obsolete = await retriever.search(
        query, groups=EVERYONE, mode=mode, k=20, include_obsolete=True
    )

    assert "NOR-004" not in {r.doc_id for r in current_only}
    assert "NOR-004" in {r.doc_id for r in with_obsolete}
    assert {r.status for r in with_obsolete if r.doc_id == "NOR-004"} == {"obsoleto"}


async def test_employee_without_groups_gets_nothing(retriever: Retriever) -> None:
    assert await retriever.search("comisión", groups=frozenset(), mode=RetrievalMode.HYBRID) == []


async def test_bm25_finds_the_exact_product_code(retriever: Retriever) -> None:
    results = await retriever.search(
        "TIN del PRS-CONS-36", groups=EVERYONE, mode=RetrievalMode.BM25
    )

    assert (results[0].doc_id, results[0].section) == ("NOR-002", "2")


async def test_query_made_only_of_stopwords_returns_nothing_lexically(retriever: Retriever) -> None:
    assert await retriever.search("¿de la que?", groups=EVERYONE, mode=RetrievalMode.BM25) == []


async def test_hybrid_returns_k_ranked_results_with_component_ranks(retriever: Retriever) -> None:
    results = await retriever.search(
        "plazo de resolución de una incidencia P2", groups=EVERYONE, mode=RetrievalMode.HYBRID, k=5
    )

    assert [r.rank for r in results] == [1, 2, 3, 4, 5]
    assert all(set(r.component_ranks) == {"dense", "bm25"} for r in results)
    assert all(r.component_ranks["dense"] or r.component_ranks["bm25"] for r in results)


async def test_sql_bm25_matches_a_python_reference(
    retriever: Retriever, pool: AsyncConnectionPool
) -> None:
    """The SQL implementation must score exactly like textbook Okapi BM25 over the visible set."""
    query = "comisión de mantenimiento de la cuenta nómina"
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT c.chunk_id, c.search_text FROM chunks c JOIN documents d USING (doc_id) "
            "WHERE d.groups && %s::text[] AND d.status = 'vigente'",
            (sorted(EVERYONE),),
        )
        visible = {chunk_id: lexical_terms(text) for chunk_id, text in await cursor.fetchall()}

    expected = _reference_bm25(query, visible)
    results = await retriever.search(query, groups=EVERYONE, mode=RetrievalMode.BM25, k=10)

    assert [r.chunk_id for r in results] == [chunk_id for chunk_id, _ in expected[:10]]
    for result, (_, score) in zip(results, expected, strict=False):
        assert result.score == pytest.approx(score, rel=1e-9)


def _reference_bm25(query: str, docs: dict[str, list[str]]) -> list[tuple[str, float]]:
    n = len(docs)
    avgdl = sum(len(terms) for terms in docs.values()) / n
    query_terms = set(lexical_terms(query))
    df = {t: sum(1 for terms in docs.values() if t in terms) for t in query_terms}
    scores: dict[str, float] = {}
    for chunk_id, terms in docs.items():
        tf = Counter(terms)
        score = 0.0
        for term in query_terms:
            if tf[term] == 0:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            norm = tf[term] + BM25_K1 * (1 - BM25_B + BM25_B * len(terms) / avgdl)
            score += idf * tf[term] * (BM25_K1 + 1) / norm
        if score > 0:
            scores[chunk_id] = score
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
