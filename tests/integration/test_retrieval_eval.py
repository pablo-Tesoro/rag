"""The retrieval evaluation runs end to end (with a fake embedder: numbers are meaningless,
the point is that every case is scored and the report is produced)."""

import psycopg
from psycopg_pool import AsyncConnectionPool

from bank_assistant.identity import EmployeeDirectory
from bank_assistant.ingestion.chunking import ChunkConfig
from bank_assistant.ingestion.pipeline import ingest_corpus
from bank_assistant.retrieval import RetrievalMode
from bank_assistant.retrieval.retriever import Retriever
from evals.retrieval_eval import DATASET, evaluate, render_markdown, summarise
from evals.schema import load_dataset
from tests.fakes import HashingEmbedder
from tests.helpers import DATA_DIR


async def test_every_labelled_case_is_scored_in_every_mode(
    schema_conninfo: str, pool: AsyncConnectionPool
) -> None:
    async with await psycopg.AsyncConnection.connect(schema_conninfo) as conn:
        await ingest_corpus(conn, DATA_DIR / "corpus", HashingEmbedder(), ChunkConfig(200, 30))
    cases = [c for c in load_dataset(DATASET) if c.relevant]
    retriever = Retriever(pool, HashingEmbedder())

    results = await evaluate(
        retriever,
        cases,
        EmployeeDirectory.from_file(DATA_DIR / "employees.json"),
        list(RetrievalMode),
        k=5,
    )
    summary = summarise(results)

    assert len(results) == 3 * len(cases)
    assert set(summary) == {"dense", "bm25", "hybrid"}
    assert all(0.0 <= row["recall"] <= 1.0 for row in summary.values())
    config = {
        "split": "all",
        "commit": "x",
        "dataset_sha256": "y",
        "embedding_model": "fake",
        "chunk_max_tokens": 200,
        "chunk_overlap_tokens": 30,
    }
    assert "| hybrid |" in render_markdown(summary, config, k=5)
