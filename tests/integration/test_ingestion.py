import shutil
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from bank_assistant.ingestion.chunking import ChunkConfig
from bank_assistant.ingestion.pipeline import INGESTION_LOCK_KEY, ingest_corpus
from tests.fakes import HashingEmbedder
from tests.helpers import DATA_DIR

CONFIG = ChunkConfig(max_tokens=200, overlap_tokens=30)


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("corpus")
    shutil.copytree(DATA_DIR / "corpus", target, dirs_exist_ok=True)
    return target


async def _count(conn: psycopg.AsyncConnection, table: str) -> int:
    cursor = await conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
    row = await cursor.fetchone()
    assert row is not None
    return int(row[0])


# The tests below run in order and share one schema: each step builds on the previous one.


async def test_first_run_adds_every_document(schema_conninfo: str, corpus: Path) -> None:
    async with await psycopg.AsyncConnection.connect(schema_conninfo) as conn:
        report = await ingest_corpus(conn, corpus, HashingEmbedder(), CONFIG)

        assert len(report.added) == 13
        assert report.updated == report.deleted == report.unchanged == []
        assert await _count(conn, "documents") == 13
        assert await _count(conn, "chunks") == report.chunks_written
        assert await _count(conn, "chunk_terms") > 0


async def test_second_run_with_no_changes_does_nothing(schema_conninfo: str, corpus: Path) -> None:
    async with await psycopg.AsyncConnection.connect(schema_conninfo) as conn:
        report = await ingest_corpus(conn, corpus, HashingEmbedder(), CONFIG)

    assert len(report.unchanged) == 13
    assert report.added == report.updated == report.deleted == []
    assert report.chunks_written == 0


async def test_only_the_modified_document_is_reprocessed(
    schema_conninfo: str, corpus: Path
) -> None:
    path = next(corpus.glob("NOR-007_*.md"))
    path.write_text(
        path.read_text(encoding="utf-8").replace("15 días hábiles", "10 días hábiles"),
        encoding="utf-8",
    )
    async with await psycopg.AsyncConnection.connect(schema_conninfo) as conn:
        report = await ingest_corpus(conn, corpus, HashingEmbedder(), CONFIG)
        cursor = await conn.execute(
            "SELECT count(*) FROM chunks "
            "WHERE doc_id = 'NOR-007' AND content LIKE '%10 días hábiles%'"
        )
        row = await cursor.fetchone()

    assert report.updated == ["NOR-007"]
    assert len(report.unchanged) == 12
    assert row is not None and row[0] == 1


async def test_deleted_files_are_removed_with_their_chunks(
    schema_conninfo: str, corpus: Path
) -> None:
    next(corpus.glob("NOR-013_*.md")).unlink()
    async with await psycopg.AsyncConnection.connect(schema_conninfo) as conn:
        report = await ingest_corpus(conn, corpus, HashingEmbedder(), CONFIG)
        cursor = await conn.execute(
            "SELECT count(*) FROM chunk_terms t JOIN chunks c USING (chunk_id) "
            "WHERE c.doc_id = 'NOR-013'"
        )
        orphan_terms = await cursor.fetchone()

        assert report.deleted == ["NOR-013"]
        assert await _count(conn, "documents") == 12
        assert orphan_terms is not None and orphan_terms[0] == 0


async def test_changing_the_embedding_model_reprocesses_everything(
    schema_conninfo: str, corpus: Path
) -> None:
    async with await psycopg.AsyncConnection.connect(schema_conninfo) as conn:
        report = await ingest_corpus(conn, corpus, HashingEmbedder(version="2"), CONFIG)

    assert len(report.updated) == 12
    assert report.unchanged == []


async def test_a_concurrent_ingestion_fails_fast(schema_conninfo: str, corpus: Path) -> None:
    async with (
        await psycopg.AsyncConnection.connect(schema_conninfo, autocommit=True) as holder,
        await psycopg.AsyncConnection.connect(schema_conninfo) as conn,
    ):
        await holder.execute("SELECT pg_advisory_lock(%s)", (INGESTION_LOCK_KEY,))
        with pytest.raises(RuntimeError, match="already running"):
            await ingest_corpus(conn, corpus, HashingEmbedder(), CONFIG)
        await holder.execute("SELECT pg_advisory_unlock(%s)", (INGESTION_LOCK_KEY,))
