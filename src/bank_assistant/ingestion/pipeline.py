"""Incremental ingestion: only what changed is re-processed, and deletions propagate.

For each corpus file we compute `content_hash = sha256(index fingerprint + file bytes
[+ PDF sidecar])`. The fingerprint covers everything that shapes the index (chunker
version and limits, lexical analyser, embedding model), so changing any of them re-processes
every document without a separate "rebuild" command.

Each document is replaced inside its own transaction (delete + insert), so a crash leaves
every document either fully old or fully new. A Postgres advisory lock makes a second,
concurrent ingestion fail fast instead of interleaving with the first.
"""

import asyncio
import hashlib
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from psycopg import AsyncConnection

from bank_assistant.db import vector_literal
from bank_assistant.embeddings import Embedder
from bank_assistant.ingestion.chunking import CHUNKER_VERSION, Chunk, ChunkConfig, chunk_document
from bank_assistant.ingestion.loaders import load_document
from bank_assistant.ingestion.metadata import SourceDocument, discover_corpus, pdf_sidecar_path
from bank_assistant.retrieval.lexical import LEXICAL_VERSION, lexical_terms

log = logging.getLogger(__name__)

# Arbitrary constant identifying "the ingestion job" for pg_advisory_lock.
INGESTION_LOCK_KEY = 7_406_001


@dataclass
class IngestReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    chunks_written: int = 0


def index_fingerprint(embedder: Embedder, config: ChunkConfig) -> str:
    parts = [
        f"chunker={CHUNKER_VERSION}",
        f"max_tokens={config.max_tokens}",
        f"overlap={config.overlap_tokens}",
        f"lexical={LEXICAL_VERSION}",
        f"embedder={embedder.model_id}",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def content_hash(source: SourceDocument, fingerprint: str) -> str:
    digest = hashlib.sha256(fingerprint.encode("utf-8"))
    digest.update(source.path.read_bytes())
    if source.kind == "pdf":
        digest.update(pdf_sidecar_path(source.path).read_bytes())
    return digest.hexdigest()


async def ingest_corpus(
    conn: AsyncConnection, corpus_dir: Path, embedder: Embedder, config: ChunkConfig
) -> IngestReport:
    sources = discover_corpus(corpus_dir)
    ids = [source.metadata.id for source in sources]
    duplicates = {doc_id for doc_id in ids if ids.count(doc_id) > 1}
    if duplicates:
        raise ValueError(f"Duplicate document ids in the corpus: {sorted(duplicates)}")

    fingerprint = index_fingerprint(embedder, config)
    report = IngestReport()
    cursor = await conn.execute("SELECT pg_try_advisory_lock(%s)", (INGESTION_LOCK_KEY,))
    acquired = await cursor.fetchone()
    if not acquired or not acquired[0]:
        raise RuntimeError("Another ingestion is already running; try again when it finishes.")
    try:
        cursor = await conn.execute("SELECT doc_id, content_hash FROM documents")
        existing = {doc_id: stored_hash for doc_id, stored_hash in await cursor.fetchall()}
        await conn.commit()

        for source in sources:
            doc_id = source.metadata.id
            new_hash = content_hash(source, fingerprint)
            if existing.get(doc_id) == new_hash:
                report.unchanged.append(doc_id)
                continue
            written = await _replace_document(conn, source, new_hash, embedder, config)
            report.chunks_written += written
            (report.updated if doc_id in existing else report.added).append(doc_id)
            log.info(
                "ingest.document",
                extra={
                    "fields": {
                        "doc_id": doc_id,
                        "chunks": written,
                        "action": "updated" if doc_id in existing else "added",
                    }
                },
            )

        stale = sorted(set(existing) - set(ids))
        if stale:
            async with conn.transaction():
                await conn.execute("DELETE FROM documents WHERE doc_id = ANY(%s)", (stale,))
            report.deleted.extend(stale)
            log.info("ingest.deleted", extra={"fields": {"doc_ids": stale}})
    finally:
        await conn.execute("SELECT pg_advisory_unlock(%s)", (INGESTION_LOCK_KEY,))
        await conn.commit()
    return report


async def _replace_document(
    conn: AsyncConnection,
    source: SourceDocument,
    new_hash: str,
    embedder: Embedder,
    config: ChunkConfig,
) -> int:
    document = load_document(source)
    chunks = chunk_document(document, embedder.count_tokens, config)
    # Embedding is CPU-bound: run it off the event loop.
    vectors = await asyncio.to_thread(embedder.embed_documents, [c.search_text for c in chunks])
    meta = document.metadata

    async with conn.transaction():
        await conn.execute("DELETE FROM documents WHERE doc_id = %s", (meta.id,))
        await conn.execute(
            """
            INSERT INTO documents
                (doc_id, title, version, doc_date, status, groups, source_path, content_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                meta.id,
                meta.title,
                meta.version,
                meta.date,
                meta.status.value,
                sorted(meta.groups),
                source.path.name,
                new_hash,
            ),
        )
        async with conn.cursor() as cursor:
            await cursor.executemany(
                """
                INSERT INTO chunks (chunk_id, doc_id, ordinal, section, section_title,
                    heading_path, content, search_text, token_count, term_count, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                """,
                [_chunk_row(chunk, vector) for chunk, vector in zip(chunks, vectors, strict=True)],
            )
            async with cursor.copy("COPY chunk_terms (term, chunk_id, tf) FROM STDIN") as copy:
                for chunk in chunks:
                    for term, tf in Counter(lexical_terms(chunk.search_text)).items():
                        await copy.write_row((term, chunk.chunk_id, tf))
    return len(chunks)


def _chunk_row(chunk: Chunk, vector: list[float]) -> tuple[object, ...]:
    return (
        chunk.chunk_id,
        chunk.doc_id,
        chunk.ordinal,
        chunk.section,
        chunk.section_title,
        chunk.heading_path,
        chunk.content,
        chunk.search_text,
        chunk.token_count,
        len(lexical_terms(chunk.search_text)),
        vector_literal(vector),
    )
