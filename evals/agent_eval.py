"""Agent evaluation harness: runs dataset cases through the real agent, scores them with
code checks and an LLM judge, and applies the quality gate.

    uv run python -m evals.agent_eval --split dev --limit 3       # quick run
    uv run python -m evals.agent_eval --split dev --repeat 3      # pass^3 on dev

Each LLM (agent and judge) goes through its own client-side rate limiter and retries 429s
with backoff, so a run fits the free tier. The report (JSON with every run in detail, and a
Markdown summary) is written to `evals/results/`. The exit code is 1 when the gate fails,
so CI can use it. The `test` split is held out: it only runs when asked for explicitly.
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.rate_limiters import InMemoryRateLimiter

from bank_assistant.agent.graph import AgentDeps
from bank_assistant.config import Settings, get_settings
from bank_assistant.identity import EmployeeDirectory
from bank_assistant.logs import configure_logging
from bank_assistant.retrieval import RetrievalMode
from evals.costs import load_prices
from evals.judge import Judge, Judgement, needs_judge
from evals.metrics.agent import QualityGate, RunRecord, score_run, summarise
from evals.report import percentile, render_markdown
from evals.runinfo import RESULTS_DIR, file_sha256, git_commit, run_id
from evals.runner import CaseRun, run_case
from evals.schema import EvalCase, load_dataset

DATASET = Path(__file__).with_name("dataset.jsonl")


class CaseJudge(Protocol):
    async def judge(self, case: EvalCase, run: CaseRun) -> Judgement: ...


def select_cases(
    cases: Sequence[EvalCase], split: str, ids: Sequence[str] | None, limit: int | None
) -> list[EvalCase]:
    selected = [c for c in cases if split == "all" or c.split == split]
    if ids:
        available = {c.id for c in selected}
        unknown = sorted(set(ids) - available)
        if unknown:
            raise ValueError(f"cases not in split '{split}': {', '.join(unknown)}")
        selected = [c for c in selected if c.id in set(ids)]
    return selected[:limit] if limit else selected


async def evaluate(
    deps: AgentDeps,
    judge: CaseJudge,
    cases: Sequence[EvalCase],
    employees: EmployeeDirectory,
    *,
    mode: RetrievalMode,
    repeats: int = 1,
    concurrency: int = 1,
    recursion_limit: int = 20,
    metadata: dict[str, Any] | None = None,
    on_result: Callable[[RunRecord], None] | None = None,
) -> list[RunRecord]:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(case: EvalCase, repeat: int) -> RunRecord:
        employee = employees.get(case.employee_id)
        if employee is None:
            raise ValueError(f"{case.id}: unknown employee {case.employee_id}")
        async with semaphore:
            run = await run_case(
                deps,
                case,
                employee,
                mode=mode,
                repeat=repeat,
                recursion_limit=recursion_limit,
                metadata=metadata,
            )
            judgement: Judgement | None = None
            judge_error = None
            if needs_judge(case, run):
                try:
                    judgement = await judge.judge(case, run)
                except Exception as error:  # reported as an error: the run was not judged
                    judge_error = f"judge {type(error).__name__}: {str(error)[:300]}"
        record = RunRecord(
            run=run,
            score=score_run(case, run, judgement.scores if judgement else None, judge_error),
            judge_input_tokens=judgement.input_tokens if judgement else 0,
            judge_output_tokens=judgement.output_tokens if judgement else 0,
        )
        if on_result:
            on_result(record)
        return record

    # Repeat-major order: every case runs once before any case runs a second time.
    return list(await asyncio.gather(*(one(c, r) for r in range(1, repeats + 1) for c in cases)))


def usage_and_cost(
    records: Sequence[RunRecord], agent_model: str, judge_model: str
) -> dict[str, Any]:
    prices = load_prices()
    agent_in = sum(r.run.input_tokens for r in records)
    agent_out = sum(r.run.output_tokens for r in records)
    judge_in = sum(r.judge_input_tokens for r in records)
    judge_out = sum(r.judge_output_tokens for r in records)
    latencies = [r.run.latency_s for r in records if r.run.error is None]
    return {
        "llm_calls_agent": sum(r.run.llm_calls for r in records),
        "agent_tokens": {"input": agent_in, "output": agent_out},
        "judge_tokens": {"input": judge_in, "output": judge_out},
        "agent_cost_usd": prices.cost(agent_model, agent_in, agent_out),
        "judge_cost_usd": prices.cost(judge_model, judge_in, judge_out),
        "prices": {"source": prices.source, "retrieved": prices.retrieved},
        "latency_s": {"p50": percentile(latencies, 50), "p95": percentile(latencies, 95)},
    }


def record_to_json(record: RunRecord) -> dict[str, Any]:
    run, score = record.run, record.score
    return {
        "case_id": run.case_id,
        "repeat": run.repeat,
        "passed": score.passed,
        "failed_checks": score.failed_checks,
        "checks": score.checks,
        "error": score.error,
        "answer": run.answer,
        "tool_calls": [asdict(c) for c in run.tool_calls],
        "retrieved": sorted({f"{r.doc_id} §{r.section}" for r in run.retrieved}),
        "evidence_recall": score.evidence_recall,
        "proposals": run.proposals,
        "incidents_before_decision": run.incidents_before_decision,
        "incidents_created": run.incidents_created,
        "judge": asdict(score.judge) if score.judge else None,
        "llm_calls": run.llm_calls,
        "tokens": {"input": run.input_tokens, "output": run.output_tokens},
        "judge_tokens": {"input": record.judge_input_tokens, "output": record.judge_output_tokens},
        "latency_s": round(run.latency_s, 2),
        "evidence": run.evidence,
    }


def _progress(total: int) -> Callable[[RunRecord], None]:
    done = 0

    def report(record: RunRecord) -> None:
        nonlocal done
        done += 1
        score = record.score
        status = "ERROR" if score.error else ("pass" if score.passed else "FAIL")
        detail = score.error or ", ".join(score.failed_checks)
        print(
            f"[{done}/{total}] {score.case_id} #{score.repeat} {status} "
            f"{record.run.latency_s:.1f}s {detail}",
            flush=True,
        )

    return report


async def main_async(settings: Settings, args: argparse.Namespace) -> int:
    # Heavy imports only when running (the embedding model, the DB, the LLM clients).
    from bank_assistant.db import open_pool
    from bank_assistant.llm import build_chat_model
    from bank_assistant.prompts import load_prompt
    from bank_assistant.services import agent_deps, build_embedder

    cases = select_cases(load_dataset(DATASET), args.split, args.cases, args.limit)
    if not cases:
        raise SystemExit("No cases selected.")
    mode = RetrievalMode(args.retrieval_mode or settings.retrieval_mode)
    prompt = load_prompt(settings.prompts_dir, "agent_system", args.prompt_version)
    judge_prompt = load_prompt(settings.prompts_dir, "eval_judge", settings.judge_prompt_version)
    per_second = settings.eval_requests_per_minute / 60

    def rate_limited_model(model: str) -> BaseChatModel:
        return build_chat_model(
            model,
            timeout_s=settings.llm_timeout_s,
            max_retries=settings.eval_llm_attempts,
            temperature=settings.llm_temperature,
            rate_limiter=InMemoryRateLimiter(
                requests_per_second=per_second, check_every_n_seconds=0.1, max_bucket_size=1
            ),
        )

    config = {
        "split": args.split,
        "cases": [c.id for c in cases],
        "partial": bool(args.limit or args.cases),
        "repeats": args.repeat,
        "commit": git_commit(),
        "dataset_sha256": file_sha256(DATASET),
        "agent_model": settings.llm_model,
        "agent_prompt": prompt.label,
        "judge_model": settings.judge_model,
        "judge_prompt": judge_prompt.label,
        "retrieval_mode": mode.value,
        "top_k": settings.retrieval_top_k,
        "embedding_model": settings.embedding_model,
        "requests_per_minute": settings.eval_requests_per_minute,
        "concurrency": args.concurrency,
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    print(f"Evaluating {len(cases)} case(s) x {args.repeat} on {mode.value}, {prompt.label}")

    pool = await open_pool(settings.database_url)
    try:
        embedder = await asyncio.to_thread(build_embedder, settings)
        deps = agent_deps(settings, pool, embedder, rate_limited_model(settings.llm_model), prompt)
        judge = Judge(rate_limited_model(settings.judge_model), judge_prompt)
        records = await evaluate(
            deps,
            judge,
            cases,
            EmployeeDirectory.from_file(settings.employees_file),
            mode=mode,
            repeats=args.repeat,
            concurrency=args.concurrency,
            recursion_limit=settings.agent_recursion_limit,
            metadata={"agent_prompt": prompt.label, "retrieval_mode": mode.value},
            on_result=_progress(len(cases) * args.repeat),
        )
    finally:
        await pool.close()

    summary = summarise([r.score for r in records])
    reasons = QualityGate().evaluate(summary)
    usage = usage_and_cost(records, settings.llm_model, settings.judge_model)
    name = run_id(f"agent_{args.split}")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "config": config,
        "gate": {"passed": not reasons, "reasons": reasons, **asdict(QualityGate())},
        "summary": summary,
        "usage": usage,
        "runs": [record_to_json(r) for r in records],
    }
    (RESULTS_DIR / f"{name}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    markdown = render_markdown(config, summary, reasons, usage, records)
    (RESULTS_DIR / f"{name}.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"Saved evals/results/{name}.json and .md")
    return 0 if not reasons else 1


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    parser.add_argument("--cases", nargs="+", metavar="ID", help="Only these case ids.")
    parser.add_argument("--limit", type=int, help="Only the first N selected cases.")
    parser.add_argument("--repeat", type=int, default=1, help="Runs per case (pass^k).")
    parser.add_argument("--concurrency", type=int, default=settings.eval_concurrency)
    parser.add_argument("--retrieval-mode", choices=[m.value for m in RetrievalMode])
    parser.add_argument("--prompt-version", default=settings.prompt_version)
    args = parser.parse_args()
    if args.repeat < 1 or args.concurrency < 1:
        parser.error("--repeat and --concurrency must be at least 1")
    configure_logging("WARNING")  # keep the console for progress lines
    sys.exit(asyncio.run(main_async(settings, args)))


if __name__ == "__main__":
    main()
