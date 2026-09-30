"""Retrieval-only evaluation: recall@k and MRR per retrieval mode. No LLM calls, so it is
free and deterministic; it isolates retrieval quality from the agent.

It asks the raw question as the employee who owns the case (their groups apply) and
includes obsolete documents only when the case expects the agent to request them.

    uv run python -m evals.retrieval_eval --modes dense bm25 hybrid --split dev
"""

import argparse
import asyncio
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from bank_assistant.config import Settings, get_settings
from bank_assistant.db import open_pool
from bank_assistant.identity import EmployeeDirectory
from bank_assistant.retrieval import RetrievalMode
from bank_assistant.retrieval.retriever import Retriever
from evals.metrics.retrieval import score_ranking
from evals.runinfo import RESULTS_DIR, file_sha256, git_commit, run_id
from evals.schema import EvalCase, load_dataset

DATASET = Path(__file__).with_name("dataset.jsonl")
MRR_DEPTH = 10


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    category: str
    mode: str
    recall: float
    reciprocal_rank: float
    retrieved: list[str]  # "NOR-002 §2" for the top results, for debugging


def wants_obsolete(case: EvalCase) -> bool:
    return any(call.args.get("incluir_obsoletos") is True for call in case.expected_tool_calls)


async def evaluate(
    retriever: Retriever,
    cases: list[EvalCase],
    employees: EmployeeDirectory,
    modes: list[RetrievalMode],
    k: int,
) -> list[CaseResult]:
    results = []
    for mode in modes:
        for case in cases:
            employee = employees.get(case.employee_id)
            if employee is None:
                raise ValueError(f"{case.id}: unknown employee {case.employee_id}")
            ranked = await retriever.search(
                case.question,
                groups=employee.groups,
                mode=mode,
                k=max(k, MRR_DEPTH),
                include_obsolete=wants_obsolete(case),
            )
            score = score_ranking(ranked, case.relevant, k)
            results.append(
                CaseResult(
                    case_id=case.id,
                    category=case.category.value,
                    mode=mode.value,
                    recall=score.recall,
                    reciprocal_rank=score.reciprocal_rank,
                    retrieved=[f"{c.doc_id} §{c.section}" for c in ranked[:k]],
                )
            )
    return results


def summarise(results: list[CaseResult]) -> dict[str, dict[str, Any]]:
    by_mode: dict[str, list[CaseResult]] = defaultdict(list)
    for result in results:
        by_mode[result.mode].append(result)
    summary: dict[str, dict[str, Any]] = {}
    for mode, items in by_mode.items():
        by_category: dict[str, list[CaseResult]] = defaultdict(list)
        for item in items:
            by_category[item.category].append(item)
        summary[mode] = {
            "cases": len(items),
            "recall": mean(i.recall for i in items),
            "mrr": mean(i.reciprocal_rank for i in items),
            "recall_by_category": {
                cat: mean(i.recall for i in group) for cat, group in sorted(by_category.items())
            },
        }
    return summary


def render_markdown(summary: dict[str, dict[str, Any]], config: dict[str, Any], k: int) -> str:
    lines = [
        f"# Retrieval evaluation ({config['split']})",
        "",
        f"- Commit: `{config['commit']}` · dataset `{config['dataset_sha256']}`",
        f"- Embedding model: `{config['embedding_model']}`",
        f"- Chunking: max {config['chunk_max_tokens']} tokens, "
        f"overlap {config['chunk_overlap_tokens']}",
        "",
        f"| Mode | Cases | Recall@{k} | MRR@{MRR_DEPTH} |",
        "|---|---|---|---|",
    ]
    for mode, row in summary.items():
        lines.append(f"| {mode} | {row['cases']} | {row['recall']:.3f} | {row['mrr']:.3f} |")
    categories = sorted({c for row in summary.values() for c in row["recall_by_category"]})
    lines += [
        "",
        f"Recall@{k} by category:",
        "",
        "| Category | " + " | ".join(summary) + " |",
        "|---|" + "---|" * len(summary),
    ]
    for category in categories:
        cells = [
            f"{summary[m]['recall_by_category'].get(category, float('nan')):.3f}" for m in summary
        ]
        lines.append(f"| {category} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


async def main_async(settings: Settings, args: argparse.Namespace) -> None:
    from bank_assistant.services import build_embedder  # loads the model: only when running

    cases = [
        c
        for c in load_dataset(DATASET)
        if c.relevant and (args.split == "all" or c.split == args.split)
    ]
    employees = EmployeeDirectory.from_file(settings.employees_file)
    pool = await open_pool(settings.database_url)
    try:
        retriever = Retriever(
            pool,
            build_embedder(settings),
            candidates=settings.retrieval_candidates,
            rrf_k=settings.rrf_k,
        )
        modes = [RetrievalMode(m) for m in args.modes]
        results = await evaluate(retriever, cases, employees, modes, args.k)
    finally:
        await pool.close()

    config = {
        "split": args.split,
        "k": args.k,
        "modes": args.modes,
        "commit": git_commit(),
        "dataset_sha256": file_sha256(DATASET),
        "embedding_model": settings.embedding_model,
        "chunk_max_tokens": settings.chunk_max_tokens,
        "chunk_overlap_tokens": settings.chunk_overlap_tokens,
        "retrieval_candidates": settings.retrieval_candidates,
        "rrf_k": settings.rrf_k,
    }
    summary = summarise(results)
    name = run_id(f"retrieval_{args.split}")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"{name}.json").write_text(
        json.dumps(
            {"config": config, "summary": summary, "cases": [asdict(r) for r in results]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    markdown = render_markdown(summary, config, args.k)
    (RESULTS_DIR / f"{name}.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"Saved evals/results/{name}.json and .md")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=[m.value for m in RetrievalMode],
        default=[m.value for m in RetrievalMode],
    )
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    parser.add_argument("--k", type=int, default=5)
    asyncio.run(main_async(get_settings(), parser.parse_args()))


if __name__ == "__main__":
    main()
