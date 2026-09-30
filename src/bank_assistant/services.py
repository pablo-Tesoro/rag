"""Wiring of the real dependencies, shared by the CLI and the API.

Everything external (LLM, embedder, database) is created here and injected into the rest
of the code, which only sees protocols. Tests call `open_services` with fakes for the LLM
and the embedder but real Postgres, or skip this module entirely.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from bank_assistant.agent.graph import AgentDeps, build_graph
from bank_assistant.agent.state import AgentContext, AgentState
from bank_assistant.config import Settings
from bank_assistant.core_banking.repository import CoreBankingRepository
from bank_assistant.db import apply_schema, open_pool
from bank_assistant.embeddings import Embedder, SentenceTransformerEmbedder
from bank_assistant.identity import EmployeeDirectory
from bank_assistant.incidents.repository import IncidentRepository
from bank_assistant.ingestion.chunking import ChunkConfig
from bank_assistant.llm import build_chat_model
from bank_assistant.prompts import Prompt, load_prompt
from bank_assistant.retrieval.retriever import Retriever

AgentGraph = CompiledStateGraph[AgentState, AgentContext, AgentState, AgentState]

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


def agent_deps(
    settings: Settings,
    pool: AsyncConnectionPool,
    embedder: Embedder,
    llm: BaseChatModel,
    prompt: Prompt,
) -> AgentDeps:
    """The agent's real dependencies. Shared by the API and the evaluation harness, so the
    harness evaluates the same wiring that is deployed."""
    return AgentDeps(
        llm=llm,
        search=Retriever(
            pool, embedder, candidates=settings.retrieval_candidates, rrf_k=settings.rrf_k
        ),
        operations=CoreBankingRepository(pool),
        incidents=IncidentRepository(pool),
        system_prompt=prompt,
        top_k=settings.retrieval_top_k,
        tool_timeout_s=settings.tool_timeout_s,
        max_tool_calls_per_turn=settings.max_tool_calls_per_turn,
    )


@dataclass(frozen=True)
class Services:
    settings: Settings
    # None when the LLM could not be configured (e.g. no API key): the process stays alive
    # (liveness) but reports not ready and refuses chat requests with a clear reason.
    graph: AgentGraph | None
    employees: EmployeeDirectory
    prompt: Prompt
    readiness: Callable[[], Awaitable[dict[str, bool]]]
    unavailable_reason: str | None = None


@asynccontextmanager
async def open_services(
    settings: Settings,
    *,
    llm: BaseChatModel | None = None,
    embedder: Embedder | None = None,
) -> AsyncIterator[Services]:
    pool = await open_pool(settings.database_url)
    # The checkpointer needs autocommit connections without prepared statements.
    checkpoint_pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        settings.database_url,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    try:
        await checkpoint_pool.open(wait=True, timeout=10)
        async with pool.connection() as conn:
            await apply_schema(conn)
        checkpointer = AsyncPostgresSaver(checkpoint_pool)
        await checkpointer.setup()

        # Loading the embedding model takes seconds of CPU: keep it off the event loop.
        search_embedder: Embedder = (
            embedder if embedder is not None else await asyncio.to_thread(build_embedder, settings)
        )
        prompt = load_prompt(settings.prompts_dir, "agent_system", settings.prompt_version)
        unavailable_reason = None
        if llm is None:
            try:
                llm = build_chat_model(
                    settings.llm_model,
                    timeout_s=settings.llm_timeout_s,
                    max_retries=settings.llm_max_retries,
                    temperature=settings.llm_temperature,
                )
            except (ValueError, ImportError) as error:  # missing key or provider package
                # The error text can echo configuration: keep it out of responses and logs.
                unavailable_reason = (
                    f"LLM not configured ({settings.llm_model}): check the provider API key "
                    "(GOOGLE_API_KEY for Gemini) and the LLM_MODEL setting."
                )
                log.error(
                    "llm.unavailable",
                    extra={"fields": {"model": settings.llm_model, "error": type(error).__name__}},
                )
        graph: AgentGraph | None = None
        if llm is not None:
            deps = agent_deps(settings, pool, search_embedder, llm, prompt)
            graph = build_graph(deps, checkpointer=checkpointer)

        async def readiness() -> dict[str, bool]:
            checks = {
                "database": False,
                "index_loaded": False,
                "core_banking_loaded": False,
                "llm_configured": graph is not None,
            }
            try:
                async with pool.connection() as conn:
                    cursor = await conn.execute(
                        "SELECT (SELECT count(*) FROM documents), "
                        "(SELECT count(*) FROM core_operations)"
                    )
                    row = await cursor.fetchone()
                checks["database"] = True
                checks["index_loaded"] = bool(row and row[0] > 0)
                checks["core_banking_loaded"] = bool(row and row[1] > 0)
            except Exception:  # readiness must answer, not raise
                checks["database"] = False
            return checks

        yield Services(
            settings=settings,
            graph=graph,
            employees=EmployeeDirectory.from_file(settings.employees_file),
            prompt=prompt,
            readiness=readiness,
            unavailable_reason=unavailable_reason,
        )
    finally:
        await checkpoint_pool.close()
        await pool.close()
