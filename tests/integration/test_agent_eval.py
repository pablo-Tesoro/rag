"""The agent harness runs every dataset case end to end on the real wiring (Postgres index
with its permission filters, core banking, agent graph), with a rule-based LLM and a fixed
judge. Scores are meaningless; the point is that every case runs, the safety checks see
real data and the report is produced."""

from pathlib import Path

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

from bank_assistant.config import Settings
from bank_assistant.core_banking.models import load_operations
from bank_assistant.core_banking.repository import CoreBankingRepository
from bank_assistant.identity import EmployeeDirectory
from bank_assistant.ingestion.chunking import ChunkConfig
from bank_assistant.ingestion.pipeline import ingest_corpus
from bank_assistant.prompts import load_prompt
from bank_assistant.retrieval import RetrievalMode
from bank_assistant.services import agent_deps
from evals.agent_eval import DATASET, evaluate, usage_and_cost
from evals.metrics.agent import QualityGate, summarise
from evals.report import render_markdown
from evals.schema import load_dataset
from tests.fakes import FixedJudge, HashingEmbedder, RuleBasedChatModel
from tests.helpers import DATA_DIR

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"


@pytest.fixture(scope="module")
async def loaded_pool(schema_conninfo: str, pool: AsyncConnectionPool) -> AsyncConnectionPool:
    async with await psycopg.AsyncConnection.connect(schema_conninfo) as conn:
        await ingest_corpus(conn, DATA_DIR / "corpus", HashingEmbedder(), ChunkConfig(200, 30))
    await CoreBankingRepository(pool).load(
        load_operations(DATA_DIR / "core_banking" / "operations.json")
    )
    return pool


async def test_every_dataset_case_runs_and_is_scored(loaded_pool: AsyncConnectionPool) -> None:
    settings = Settings(data_dir=DATA_DIR, prompts_dir=PROMPTS)
    prompt = load_prompt(PROMPTS, "agent_system", "v1")
    deps = agent_deps(settings, loaded_pool, HashingEmbedder(), RuleBasedChatModel(), prompt)
    cases = load_dataset(DATASET)

    records = await evaluate(
        deps,
        FixedJudge(),
        cases,
        EmployeeDirectory.from_file(DATA_DIR / "employees.json"),
        mode=RetrievalMode.HYBRID,
        concurrency=4,
    )

    assert len(records) == len(cases)
    assert [r.run.error for r in records] == [None] * len(cases)
    by_case = {r.score.case_id: r for r in records}
    # Approval: proposed, nothing written before the decision, then 1 (approve) or 0 (reject).
    assert by_case["APR-01"].score.checks["approval"] is True
    assert by_case["APR-01"].run.incidents_created == 1
    assert by_case["APR-02"].score.checks["approval"] is True
    assert by_case["APR-02"].run.incidents_created == 0
    # Restricted documents never reach an employee outside their group (filter in SQL).
    assert by_case["PER-01"].score.checks["forbidden_docs"] is True
    assert by_case["PER-03"].score.checks["forbidden_docs"] is True

    summary = summarise([r.score for r in records])
    assert summary["cases"] == len(cases)
    usage = usage_and_cost(records, settings.llm_model, settings.judge_model)
    config = {
        "split": "all",
        "cases": [c.id for c in cases],
        "partial": False,
        "commit": "test",
        "dataset_sha256": "test",
        "started_at": "now",
        "agent_model": "rule-based",
        "agent_prompt": prompt.label,
        "judge_model": "fixed",
        "judge_prompt": "fixed",
        "retrieval_mode": "hybrid",
        "top_k": 5,
    }
    markdown = render_markdown(config, summary, QualityGate().evaluate(summary), usage, records)
    assert markdown.startswith("# Agent evaluation (all)")
    assert "| APR-01 (critical) | 1 |" in markdown
