"""Controls for the LLM judge: answers whose verdict is known in advance.

A judge that approves everything is worse than no judge. Before trusting its numbers, it
must reject what is known to be wrong. Each control takes a dataset case, the evidence the
retriever returns for its question (no agent call, no cost besides the judge) and a
hand-written answer, and states the verdict the judge must give.

    uv run python -m evals.judge_controls

The exit code is 1 if the judge disagrees with any control.
"""

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from bank_assistant.agent.tools import format_chunks
from bank_assistant.config import Settings, get_settings
from bank_assistant.identity import EmployeeDirectory
from bank_assistant.logs import configure_logging
from bank_assistant.retrieval import RetrievalMode
from evals.judge import Judge
from evals.runinfo import RESULTS_DIR, git_commit, run_id
from evals.runner import CaseRun
from evals.schema import load_dataset

DATASET = Path(__file__).with_name("dataset.jsonl")


@dataclass(frozen=True)
class Control:
    name: str
    case_id: str
    answer: str
    correct: bool
    grounded: bool


_BASE = (
    "La Cuenta Nómina Plus (CTA-NOM-02) tiene una comisión de mantenimiento de 4,50 € al mes "
    "(NOR-001, sección 2)."
)
CONTROLS = (
    Control(
        "correct",
        "COD-01",
        _BASE + " Queda exenta si el cliente domicilia una nómina de al menos 1.200 € al mes "
        "(NOR-001, sección 5).",
        correct=True,
        grounded=True,
    ),
    Control("missing_fact", "COD-01", _BASE, correct=False, grounded=True),
    Control(
        "wrong_figure",
        "COD-01",
        _BASE + " Queda exenta si el cliente domicilia una nómina de al menos 600 € al mes "
        "(NOR-001, sección 5).",
        correct=False,
        grounded=False,
    ),
    Control(
        "invented_claim",
        "COD-01",
        _BASE + " Queda exenta si el cliente domicilia una nómina de al menos 1.200 € al mes "
        "(NOR-001, sección 5). Además, los clientes mayores de 65 años están siempre exentos.",
        correct=True,
        grounded=False,
    ),
)


async def main_async(settings: Settings) -> int:
    from bank_assistant.db import open_pool
    from bank_assistant.llm import build_chat_model
    from bank_assistant.prompts import load_prompt
    from bank_assistant.retrieval.retriever import Retriever
    from bank_assistant.services import build_embedder

    cases = {c.id: c for c in load_dataset(DATASET)}
    employees = EmployeeDirectory.from_file(settings.employees_file)
    prompt = load_prompt(settings.prompts_dir, "eval_judge", settings.judge_prompt_version)
    judge = Judge(
        build_chat_model(
            settings.judge_model,
            timeout_s=settings.llm_timeout_s,
            max_retries=settings.eval_llm_attempts,
        ),
        prompt,
    )
    pool = await open_pool(settings.database_url)
    try:
        retriever = Retriever(
            pool,
            await asyncio.to_thread(build_embedder, settings),
            candidates=settings.retrieval_candidates,
            rrf_k=settings.rrf_k,
        )
        results: list[dict[str, object]] = []
        agreements: list[bool] = []
        for control in CONTROLS:
            case = cases[control.case_id]
            employee = employees.get(case.employee_id)
            if employee is None:
                raise ValueError(f"{case.id}: unknown employee {case.employee_id}")
            chunks = await retriever.search(
                case.question, groups=employee.groups, mode=RetrievalMode.HYBRID, k=5
            )
            run = CaseRun(
                case_id=case.id,
                repeat=1,
                thread_id="control",
                evidence="[buscar_normativa]\n" + format_chunks(case.question, chunks),
                answer={"texto": control.answer, "citas": [], "sin_evidencia": False},
            )
            scores = (await judge.judge(case, run)).scores
            agrees = (scores.answer_correct, scores.grounded) == (control.correct, control.grounded)
            agreements.append(agrees)
            results.append(
                {
                    "control": control.name,
                    "case_id": case.id,
                    "expected": {"correct": control.correct, "grounded": control.grounded},
                    "judged": {"correct": scores.answer_correct, "grounded": scores.grounded},
                    "agrees": agrees,
                    "missing_facts": scores.missing_facts,
                    "unsupported_claims": scores.unsupported_claims,
                    "analysis": scores.analysis,
                }
            )
            print(
                f"{'ok  ' if agrees else 'MISS'} {control.name}: correct={scores.answer_correct} "
                f"grounded={scores.grounded}",
                flush=True,
            )
    finally:
        await pool.close()

    name = run_id("judge_controls")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "config": {
            "commit": git_commit(),
            "judge_model": settings.judge_model,
            "judge_prompt": prompt.label,
        },
        "agreement": sum(agreements) / len(agreements),
        "controls": results,
    }
    (RESULTS_DIR / f"{name}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Agreement {payload['agreement']:.2f}. Saved evals/results/{name}.json")
    return 0 if all(agreements) else 1


def main() -> None:
    configure_logging("WARNING")
    sys.exit(asyncio.run(main_async(get_settings())))


if __name__ == "__main__":
    main()
