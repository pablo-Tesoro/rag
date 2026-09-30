"""LLM judge for what code cannot decide: is the answer correct, and is it grounded?

- One yes/no verdict per key fact instead of a 1-10 score: binary questions are easier
  for a model to answer consistently, and for a person to audit. Their mean is the
  key-fact recall.
- The judge sees the tool results the agent saw, so groundedness is judged against what
  the agent actually read. Citation checks in the graph only prove that a cited source was
  retrieved, not that it says what the answer claims (D-20).
- The evidence contains the corpus' planted instruction (NOR-010 §3): the judge prompt
  treats everything inside the tags as data, like the agent's prompt does.
- The verdict is structured output validated by code: every key fact must get exactly one
  verdict, or the judgement is an error rather than a silent pass.
"""

import html
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from bank_assistant.prompts import Prompt
from evals.metrics.agent import JudgeScores
from evals.runner import CaseRun
from evals.schema import EvalCase


class FactVerdict(BaseModel):
    indice: int = Field(ge=1, description="Número del hecho clave en la lista (desde 1).")
    presente: bool = Field(description="La respuesta afirma este hecho con el mismo significado.")


class JudgeVerdict(BaseModel):
    """Veredicto sobre la respuesta del asistente."""

    analisis: str = Field(description="Razonamiento breve, antes de los veredictos.")
    hechos: list[FactVerdict] = Field(description="Un veredicto por cada hecho clave.")
    contradice_referencia: bool = Field(
        description="La respuesta afirma algo incompatible con la respuesta de referencia."
    )
    afirmaciones_sin_soporte: list[str] = Field(
        description="Afirmaciones concretas de la respuesta que no aparecen en la evidencia."
    )


class JudgeError(Exception):
    """The judge did not return a usable verdict."""


def needs_judge(case: EvalCase, run: CaseRun) -> bool:
    return bool(case.key_facts) and run.error is None and run.answer is not None


def judge_input(case: EvalCase, run: CaseRun) -> str:
    facts = "\n".join(f"{i}. {html.escape(fact)}" for i, fact in enumerate(case.key_facts, 1))
    answer = (run.answer or {}).get("texto", "")
    # The evidence is passed as the agent saw it: tool results are already escaped.
    return (
        f"<pregunta>\n{html.escape(case.question)}\n</pregunta>\n\n"
        f"<respuesta_referencia>\n{html.escape(case.reference_answer)}\n"
        "</respuesta_referencia>\n\n"
        f"<hechos_clave>\n{facts}\n</hechos_clave>\n\n"
        f"<evidencia>\n{run.evidence or '(el asistente no usó ninguna herramienta)'}\n"
        "</evidencia>\n\n"
        f"<respuesta_evaluada>\n{html.escape(str(answer))}\n</respuesta_evaluada>"
    )


def scores_from_verdict(case: EvalCase, verdict: JudgeVerdict) -> JudgeScores:
    expected = list(range(1, len(case.key_facts) + 1))
    if sorted(f.indice for f in verdict.hechos) != expected:
        given = [f.indice for f in verdict.hechos]
        raise JudgeError(f"expected one verdict for each of facts {expected}, got {given}")
    present = {f.indice: f.presente for f in verdict.hechos}
    missing = [fact for i, fact in enumerate(case.key_facts, 1) if not present[i]]
    unsupported = [claim for claim in verdict.afirmaciones_sin_soporte if claim.strip()]
    return JudgeScores(
        answer_correct=not missing and not verdict.contradice_referencia,
        grounded=not unsupported,
        key_fact_recall=1 - len(missing) / len(case.key_facts),
        missing_facts=missing,
        unsupported_claims=unsupported,
        contradicts_reference=verdict.contradice_referencia,
        analysis=verdict.analisis,
    )


@dataclass(frozen=True)
class Judgement:
    scores: JudgeScores
    input_tokens: int
    output_tokens: int


class Judge:
    def __init__(self, model: BaseChatModel, prompt: Prompt) -> None:
        self.prompt = prompt
        self._model = model.with_structured_output(JudgeVerdict, include_raw=True)

    async def judge(self, case: EvalCase, run: CaseRun) -> Judgement:
        messages = [SystemMessage(self.prompt.text), HumanMessage(judge_input(case, run))]
        result: Any = await self._model.ainvoke(messages)
        raw, parsed = result["raw"], result["parsed"]
        usage = raw.usage_metadata if isinstance(raw, AIMessage) else None
        if not isinstance(parsed, JudgeVerdict):
            raise JudgeError(f"unparseable verdict: {result.get('parsing_error')}")
        return Judgement(
            scores=scores_from_verdict(case, parsed),
            input_tokens=usage["input_tokens"] if usage else 0,
            output_tokens=usage["output_tokens"] if usage else 0,
        )
