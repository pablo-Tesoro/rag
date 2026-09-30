"""Command-line entry points.

python -m bank_assistant.cli ingest
python -m bank_assistant.cli search "¿Cuál es el límite diario...?" --employee EMP-001
"""

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict

from psycopg import AsyncConnection

from bank_assistant.config import Settings, get_settings
from bank_assistant.db import apply_schema, open_pool
from bank_assistant.embeddings import SentenceTransformerEmbedder
from bank_assistant.identity import EmployeeDirectory
from bank_assistant.ingestion.chunking import ChunkConfig
from bank_assistant.ingestion.pipeline import ingest_corpus
from bank_assistant.logs import configure_logging
from bank_assistant.retrieval import RetrievalMode
from bank_assistant.retrieval.retriever import Retriever

log = logging.getLogger(__name__)


def build_embedder(settings: Settings) -> SentenceTransformerEmbedder:
    embedder = SentenceTransformerEmbedder(
        settings.embedding_model,
        query_prefix=settings.embedding_query_prefix,
        document_prefix=settings.embedding_document_prefix,
    )
    if settings.chunk_max_tokens > embedder.max_tokens:
        raise ValueError(
            f"CHUNK_MAX_TOKENS={settings.chunk_max_tokens} exceeds the model window "
            f"({embedder.max_tokens}); chunks would be truncated when embedded."
        )
    return embedder


def chunk_config(settings: Settings) -> ChunkConfig:
    return ChunkConfig(
        max_tokens=settings.chunk_max_tokens, overlap_tokens=settings.chunk_overlap_tokens
    )


async def run_ingest(settings: Settings) -> int:
    embedder = build_embedder(settings)
    async with await AsyncConnection.connect(settings.database_url) as conn:
        await apply_schema(conn)
        report = await ingest_corpus(conn, settings.corpus_dir, embedder, chunk_config(settings))
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0


async def run_search(settings: Settings, args: argparse.Namespace) -> int:
    employee = EmployeeDirectory.from_file(settings.employees_file).get(args.employee)
    if employee is None:
        print(f"Unknown employee: {args.employee}", file=sys.stderr)
        return 2
    pool = await open_pool(settings.database_url)
    try:
        retriever = Retriever(
            pool,
            build_embedder(settings),
            candidates=settings.retrieval_candidates,
            rrf_k=settings.rrf_k,
        )
        results = await retriever.search(
            args.query,
            groups=employee.groups,
            mode=RetrievalMode(args.mode),
            k=args.k,
            include_obsolete=args.include_obsolete,
        )
    finally:
        await pool.close()
    for chunk in results:
        print(
            f"{chunk.rank}. {chunk.doc_id} §{chunk.section} [{chunk.status}] "
            f"score={chunk.score:.4f} ranks={chunk.component_ranks}\n   {chunk.heading_path}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    parser = argparse.ArgumentParser(prog="bank_assistant")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("ingest", help="Incrementally ingest data/corpus into Postgres")

    search = commands.add_parser("search", help="Run the retriever as a given employee")
    search.add_argument("query")
    search.add_argument("--employee", required=True)
    search.add_argument(
        "--mode", choices=[m.value for m in RetrievalMode], default=settings.retrieval_mode.value
    )
    search.add_argument("--k", type=int, default=settings.retrieval_top_k)
    search.add_argument("--include-obsolete", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "ingest":
        return asyncio.run(run_ingest(settings))
    return asyncio.run(run_search(settings, args))


if __name__ == "__main__":
    raise SystemExit(main())
