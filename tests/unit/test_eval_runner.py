"""The harness runs cases through the real graph (scripted LLM, in-memory fakes)."""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from bank_assistant.agent.graph import AgentDeps
from bank_assistant.identity import Employee, EmployeeDirectory
from bank_assistant.prompts import load_prompt
from bank_assistant.retrieval import RetrievalMode
from evals.agent_eval import evaluate, select_cases
from evals.metrics.agent import code_checks
from evals.runner import CaseRun, run_case
from evals.schema import EvalCase
from tests.fakes import (
    FakeIncidents,
    FakeSearch,
    FixedJudge,
    ScriptedChatModel,
    answer,
    approval_case,
    chunk,
    make_case,
    sample_operations,
    tool_call,
)

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
EMPLOYEE = Employee(
    id="EMP-001", role="Gestión comercial", office_id="0101", groups=frozenset({"todos"})
)
PROPOSAL = tool_call(
    "abrir_incidencia",
    id_operacion="OP-111111",
    categoria="cargo_duplicado",
    descripcion="Recibo cobrado dos veces",
)


def deps(script: list[AIMessage], search: FakeSearch | None = None) -> AgentDeps:
    return AgentDeps(
        llm=ScriptedChatModel(script=script),
        search=search or FakeSearch([chunk("NOR-005", "2", "Límite en oficina: 5.000 €.")]),
        operations=sample_operations(),
        incidents=FakeIncidents(),  # replaced by the harness' sandbox
        system_prompt=load_prompt(PROMPTS, "agent_system", "v1"),
    )


async def run(case: EvalCase, script: list[AIMessage]) -> CaseRun:
    return await run_case(deps(script), case, EMPLOYEE, mode=RetrievalMode.HYBRID)


async def test_a_run_records_answer_tools_retrieval_evidence_and_tokens() -> None:
    search_call = tool_call("buscar_normativa", consulta="límite oficina")
    search_call.usage_metadata = {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}
    final = answer("5.000 €.", citas=[("NOR-005", "2")])
    final.usage_metadata = {"input_tokens": 300, "output_tokens": 20, "total_tokens": 320}

    result = await run(make_case(), [search_call, final])

    assert result.error is None
    assert result.answer is not None and result.answer["texto"] == "5.000 €."
    assert [c.name for c in result.tool_calls] == ["buscar_normativa"]  # `responder` excluded
    assert [(r.doc_id, r.section) for r in result.retrieved] == [("NOR-005", "2")]
    assert result.evidence.startswith("[buscar_normativa]\n<resultados")
    assert (result.llm_calls, result.input_tokens, result.output_tokens) == (2, 400, 30)


async def test_approved_incident_is_written_once_and_only_after_the_decision() -> None:
    case = approval_case("approve")

    result = await run(case, [PROPOSAL, answer("Incidencia INC-000001 registrada.")])

    assert result.proposals[0]["id_operacion"] == "OP-111111"
    assert result.incidents_before_decision == 0
    assert result.incidents_created == 1
    assert code_checks(case, result)["approval"] is True
    approval_then_write = (
        "[aprobacion_humana]\nEl empleado aprobó la incidencia propuesta.\n\n"
        "[abrir_incidencia]\nIncidencia INC-000001 registrada"
    )
    assert approval_then_write in result.evidence


async def test_rejected_incident_is_not_written() -> None:
    case = approval_case("reject")

    result = await run(case, [PROPOSAL, answer("No se ha abierto.")])

    assert result.incidents_created == 0
    assert code_checks(case, result)["approval"] is True
    assert "El empleado rechazó la incidencia propuesta." in result.evidence


async def test_an_unrequested_proposal_is_rejected_and_caught() -> None:
    case = make_case(forbidden={"tool_calls": [{"name": "abrir_incidencia"}]})

    result = await run(case, [PROPOSAL, answer("Hecho.")])

    assert result.incidents_created == 0  # the harness never approves on its own
    assert code_checks(case, result)["forbidden_tools"] is False


async def test_a_crash_is_recorded_as_an_error_not_raised() -> None:
    result = await run(make_case(), [])  # the scripted model has nothing to say

    assert result.error is not None and result.error.startswith("AssertionError")
    assert result.answer is None


async def test_evaluate_runs_every_repeat_and_judges_only_cases_with_facts() -> None:
    factual = make_case()
    abstention = make_case(
        id="SIN-99", category="no_answer", must_abstain=True, key_facts=[], relevant=[]
    )
    script = [answer("5.000 €.", citas=[]), answer("No consta.", sin_evidencia=True)] * 2
    judge = FixedJudge()

    records = await evaluate(
        deps(script),
        judge,
        [factual, abstention],
        EmployeeDirectory([EMPLOYEE]),
        mode=RetrievalMode.HYBRID,
        repeats=2,
    )

    assert [(r.score.case_id, r.score.repeat) for r in records] == [
        ("TST-01", 1),
        ("SIN-99", 1),
        ("TST-01", 2),
        ("SIN-99", 2),
    ]
    assert judge.judged == ["TST-01#1", "TST-01#2"]
    assert all(r.score.passed for r in records)
    assert records[0].judge_input_tokens == 50


async def test_a_judge_failure_marks_the_run_as_an_error() -> None:
    records = await evaluate(
        deps([answer("5.000 €.")]),
        FixedJudge(fail=True),
        [make_case()],
        EmployeeDirectory([EMPLOYEE]),
        mode=RetrievalMode.HYBRID,
    )

    assert records[0].score.error == "judge TimeoutError: judge timed out"
    assert not records[0].score.passed


def test_test_cases_only_run_when_the_test_split_is_asked_for() -> None:
    cases = [make_case(id="DEV-01"), make_case(id="TST-02", split="test")]

    assert [c.id for c in select_cases(cases, "dev", None, None)] == ["DEV-01"]
    assert [c.id for c in select_cases(cases, "all", ["TST-02"], None)] == ["TST-02"]
    with pytest.raises(ValueError, match="TST-02"):
        select_cases(cases, "dev", ["TST-02"], None)


def test_limit_takes_the_first_selected_cases() -> None:
    cases = [make_case(id=f"DEV-0{i}") for i in range(1, 4)]

    assert [c.id for c in select_cases(cases, "dev", None, 2)] == ["DEV-01", "DEV-02"]
