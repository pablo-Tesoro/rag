"""Agent loop tests with a scripted LLM: deterministic, no network, no database."""

import uuid
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from bank_assistant.agent.graph import AgentDeps, build_graph
from bank_assistant.agent.state import AgentContext, AgentState
from bank_assistant.identity import Employee
from bank_assistant.prompts import load_prompt
from bank_assistant.retrieval import RetrievalMode
from tests.fakes import (
    FakeIncidents,
    FakeSearch,
    ScriptedChatModel,
    answer,
    chunk,
    sample_operations,
    tool_call,
)

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
EMPLOYEE = Employee(
    id="EMP-001", role="Gestión comercial", office_id="0101", groups=frozenset({"todos"})
)


class Harness:
    def __init__(self, script: list[AIMessage], **deps: Any) -> None:
        self.llm = ScriptedChatModel(script=script)
        self.search: FakeSearch = deps.pop("search", FakeSearch())
        self.incidents: FakeIncidents = deps.pop("incidents", FakeIncidents())
        self.graph = build_graph(
            AgentDeps(
                llm=self.llm,
                search=self.search,
                operations=deps.pop("operations", sample_operations()),
                incidents=self.incidents,
                system_prompt=load_prompt(PROMPTS, "agent_system", "v1"),
                **deps,
            ),
            checkpointer=InMemorySaver(),
        )
        self.config: Any = {"configurable": {"thread_id": uuid.uuid4().hex}}
        self.context = AgentContext(employee=EMPLOYEE, retrieval_mode=RetrievalMode.HYBRID)

    async def ask(self, question: str) -> dict[str, Any]:
        state: AgentState = {
            "messages": [HumanMessage(question)],
            "employee_id": EMPLOYEE.id,
            "retrieved": {},
            "final_answer": None,
        }
        return await self.graph.ainvoke(state, self.config, context=self.context)

    async def resume(self, approved: bool) -> dict[str, Any]:
        command: Command[Any] = Command(resume={"approved": approved})
        return await self.graph.ainvoke(command, self.config, context=self.context)

    @staticmethod
    def tool_messages(result: dict[str, Any]) -> list[ToolMessage]:
        return [m for m in result["messages"] if isinstance(m, ToolMessage)]


# ------------------------------------------------------------------------ retrieval + answer


async def test_rag_answer_with_citations_uses_the_employee_groups_and_mode() -> None:
    search = FakeSearch([chunk("NOR-005", "2", "Límite inmediata en oficina: 5.000 €.")])
    harness = Harness(
        [
            tool_call("buscar_normativa", consulta="límite transferencia inmediata oficina"),
            answer("5.000 € al día.", citas=[("NOR-005", "2")]),
        ],
        search=search,
    )

    result = await harness.ask("¿Cuál es el límite?")

    assert result["final_answer"] == {
        "texto": "5.000 € al día.",
        "citas": [{"documento": "NOR-005", "seccion": "2"}],
        "sin_evidencia": False,
        "terminacion": "respuesta",
    }
    assert search.calls[0]["groups"] == EMPLOYEE.groups
    assert search.calls[0]["mode"] is RetrievalMode.HYBRID
    assert search.calls[0]["include_obsolete"] is False
    tool_result = harness.tool_messages(result)[0].content
    assert '<documento id="NOR-005" seccion="2"' in str(tool_result)


async def test_the_four_tools_are_bound_with_spanish_names_and_descriptions() -> None:
    harness = Harness([answer("Hola", sin_evidencia=True)])
    await harness.ask("Hola")

    names = [tool["function"]["name"] for tool in harness.llm.bound_tools]
    assert names == ["buscar_normativa", "consultar_operacion", "abrir_incidencia", "responder"]
    assert all(tool["function"]["description"] for tool in harness.llm.bound_tools)


async def test_system_prompt_and_employee_context_are_sent_to_the_model() -> None:
    harness = Harness([answer("Hola", sin_evidencia=True)])
    await harness.ask("Hola")

    system = harness.llm.received[0][0]
    assert "asistente interno" in str(system.content)
    assert "oficina 0101" in str(system.content)


async def test_no_evidence_answers_carry_no_citations() -> None:
    harness = Harness([answer("No lo sé.", citas=[("NOR-001", "1")], sin_evidencia=True)])

    result = await harness.ask("¿Días de teletrabajo?")

    assert result["final_answer"]["sin_evidencia"] is True
    assert result["final_answer"]["citas"] == []


async def test_plain_text_answer_is_accepted_but_flagged() -> None:
    harness = Harness([AIMessage(content="Respuesta sin herramienta.")])

    result = await harness.ask("Hola")

    assert result["final_answer"]["texto"] == "Respuesta sin herramienta."
    assert result["final_answer"]["terminacion"] == "texto_libre"


# --------------------------------------------------------------------------------- citations


async def test_unsupported_citation_is_sent_back_once_for_correction() -> None:
    search = FakeSearch([chunk("NOR-007", "2", "P2: 2 días hábiles.")])
    harness = Harness(
        [
            tool_call("buscar_normativa", consulta="plazo P2"),
            answer("2 días hábiles.", citas=[("NOR-099", "1")]),  # not retrieved
            answer("2 días hábiles.", citas=[("NOR-007", "2")]),
        ],
        search=search,
    )

    result = await harness.ask("¿Plazo P2?")

    correction = [m for m in harness.tool_messages(result) if m.status == "error"]
    assert "NOR-099 §1" in str(correction[0].content)
    assert result["final_answer"]["citas"] == [{"documento": "NOR-007", "seccion": "2"}]


async def test_citations_still_unsupported_after_one_fix_are_dropped() -> None:
    search = FakeSearch([chunk("NOR-007", "2", "P2: 2 días hábiles.")])
    harness = Harness(
        [
            tool_call("buscar_normativa", consulta="plazo P2"),
            answer("2 días.", citas=[("NOR-099", "1")]),
            answer("2 días.", citas=[("NOR-007", "2"), ("NOR-099", "1")]),
        ],
        search=search,
    )

    result = await harness.ask("¿Plazo P2?")

    assert result["final_answer"]["citas"] == [{"documento": "NOR-007", "seccion": "2"}]
    assert result["final_answer"]["citas_descartadas"] == [{"documento": "NOR-099", "seccion": "1"}]


async def test_citing_a_parent_or_child_section_of_a_retrieved_chunk_is_valid() -> None:
    search = FakeSearch([chunk("NOR-001", "3.1", "Comisión de descubierto 4,5 %.")])
    harness = Harness(
        [
            tool_call("buscar_normativa", consulta="descubierto"),
            answer("4,5 %.", citas=[("NOR-001", "3")]),
        ],
        search=search,
    )

    result = await harness.ask("¿Descubierto?")

    assert result["final_answer"]["citas"] == [{"documento": "NOR-001", "seccion": "3"}]


# --------------------------------------------------------------------------- operations


async def test_operation_of_another_office_looks_exactly_like_a_missing_one() -> None:
    harness = Harness(
        [
            tool_call("consultar_operacion", id_operacion="OP-222222"),  # office 0412
            tool_call("consultar_operacion", id_operacion="OP-999999"),  # does not exist
            answer("No encontrada.", sin_evidencia=True),
        ]
    )

    result = await harness.ask("¿Estado?")

    other_office, missing = (str(m.content) for m in harness.tool_messages(result)[:2])
    assert other_office.replace("OP-222222", "X") == missing.replace("OP-999999", "X")
    assert "45.20" not in other_office


async def test_operation_content_is_escaped_as_data() -> None:
    harness = Harness(
        [tool_call("consultar_operacion", id_operacion="OP-111111"), answer("Liquidada.")]
    )

    result = await harness.ask("¿Estado de OP-111111?")

    content = str(harness.tool_messages(result)[0].content)
    assert content.count("</operacion>") == 1  # the one closing tag we wrote
    assert "&lt;/operacion&gt;" in content


async def test_the_model_cannot_choose_the_office() -> None:
    harness = Harness(
        [
            tool_call("consultar_operacion", id_operacion="OP-222222", oficina="0412"),
            answer("No puedo.", sin_evidencia=True),
        ]
    )

    result = await harness.ask("Consulta OP-222222 de la oficina 0412")

    error = harness.tool_messages(result)[0]
    assert error.status == "error"
    assert "oficina" in str(error.content)


async def test_invalid_arguments_return_an_actionable_error() -> None:
    harness = Harness(
        [
            tool_call("consultar_operacion", id_operacion="12345"),
            tool_call("consultar_operacion", id_operacion="OP-111111"),
            answer("Liquidada."),
        ]
    )

    result = await harness.ask("¿Estado de la 12345?")

    first, second = harness.tool_messages(result)[:2]
    assert first.status == "error"
    assert "OP- seguido de 6 dígitos" in str(first.content)
    assert second.status == "success"


async def test_unknown_tool_names_are_reported_to_the_model() -> None:
    harness = Harness([tool_call("borrar_todo"), answer("No puedo.", sin_evidencia=True)])

    result = await harness.ask("Borra todo")

    assert "no existe" in str(harness.tool_messages(result)[0].content)


# ------------------------------------------------------------------------------ guards


async def test_repeating_the_same_call_is_detected() -> None:
    search = FakeSearch([chunk("NOR-005", "2", "5.000 €")])
    harness = Harness(
        [
            tool_call("buscar_normativa", consulta="límite"),
            tool_call("buscar_normativa", consulta="límite"),
            answer("5.000 €.", citas=[("NOR-005", "2")]),
        ],
        search=search,
    )

    result = await harness.ask("¿Límite?")

    repeated = harness.tool_messages(result)[1]
    assert repeated.status == "error"
    assert "mismos argumentos" in str(repeated.content)
    assert len(search.calls) == 1  # the repeated call never reached the tool


async def test_tool_budget_stops_the_loop_and_closes_pending_calls() -> None:
    harness = Harness(
        [tool_call("buscar_normativa", consulta=f"consulta {i}") for i in range(3)],
        max_tool_calls_per_turn=2,
    )

    result = await harness.ask("Busca mucho")

    assert result["final_answer"]["terminacion"] == "limite_herramientas"
    assert result["final_answer"]["sin_evidencia"] is True
    calls = [c["id"] for m in result["messages"] if isinstance(m, AIMessage) for c in m.tool_calls]
    answered = {m.tool_call_id for m in harness.tool_messages(result)}
    assert set(calls) == answered  # every tool call got a response


async def test_slow_tools_time_out_with_a_recoverable_error() -> None:
    harness = Harness(
        [
            tool_call("buscar_normativa", consulta="lento"),
            answer("No disponible.", sin_evidencia=True),
        ],
        search=FakeSearch([chunk("NOR-001", "1", "x")], delay_s=0.5),
        tool_timeout_s=0.05,
    )

    result = await harness.ask("¿Algo?")

    timeout = harness.tool_messages(result)[0]
    assert timeout.status == "error"
    assert "no respondió" in str(timeout.content)


# ---------------------------------------------------------------------------- approval


async def test_incident_needs_approval_and_is_created_once_approved() -> None:
    harness = Harness(
        [
            tool_call(
                "abrir_incidencia",
                call_id="call-inc-1",
                id_operacion="OP-111111",
                categoria="cargo_duplicado",
                descripcion="Recibo cobrado dos veces",
            ),
            answer("Incidencia INC-000001 registrada."),
        ]
    )

    paused = await harness.ask("Abre una incidencia por cargo duplicado en OP-111111")

    pending = paused["__interrupt__"][0].value
    assert pending["action"] == "abrir_incidencia"
    assert pending["args"]["id_operacion"] == "OP-111111"
    assert pending["operation"]["estado"] == "LIQUIDADA"
    assert harness.incidents.requests == []  # nothing written before the human decides

    result = await harness.resume(approved=True)

    assert len(harness.incidents.by_key) == 1
    request = harness.incidents.requests[0]
    assert (request.employee_id, request.office_id) == ("EMP-001", "0101")
    assert "INC-000001" in str(harness.tool_messages(result)[-2].content)
    assert result["final_answer"]["terminacion"] == "respuesta"


async def test_rejected_incident_is_not_created() -> None:
    harness = Harness(
        [
            tool_call(
                "abrir_incidencia",
                id_operacion="OP-111111",
                categoria="importe_incorrecto",
                descripcion="Importe distinto del ordenado",
            ),
            answer("No se ha registrado la incidencia."),
        ]
    )

    await harness.ask("Abre una incidencia")
    result = await harness.resume(approved=False)

    assert harness.incidents.requests == []
    assert "rechazado" in str(harness.tool_messages(result)[0].content)


async def test_a_replayed_approval_after_a_crash_creates_a_single_incident() -> None:
    incidents = FakeIncidents(fail_after_write=True)
    harness = Harness(
        [
            tool_call(
                "abrir_incidencia",
                id_operacion="OP-111111",
                categoria="cargo_duplicado",
                descripcion="Recibo cobrado dos veces",
            ),
            answer("Registrada."),
        ],
        incidents=incidents,
    )
    await harness.ask("Abre una incidencia")

    with pytest.raises(ConnectionError):
        await harness.resume(approved=True)  # written, then "crashed" before checkpointing
    await harness.resume(approved=True)  # the node runs again from the start

    assert len(incidents.requests) == 2
    assert len(incidents.by_key) == 1  # same idempotency key: a single incident


async def test_incident_on_another_offices_operation_is_refused_without_asking() -> None:
    harness = Harness(
        [
            tool_call(
                "abrir_incidencia",
                id_operacion="OP-222222",
                categoria="otro",
                descripcion="Anomalía en la operación",
            ),
            answer("No puedo abrirla.", sin_evidencia=True),
        ]
    )

    result = await harness.ask("Abre una incidencia en OP-222222")

    assert "__interrupt__" not in result
    assert "No se puede abrir" in str(harness.tool_messages(result)[0].content)


async def test_only_one_incident_can_be_proposed_at_a_time() -> None:
    double = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "abrir_incidencia",
                "id": f"call-{i}",
                "args": {
                    "id_operacion": "OP-111111",
                    "categoria": "otro",
                    "descripcion": f"Anomalía número {i}",
                },
            }
            for i in (1, 2)
        ],
    )
    harness = Harness([double, answer("Hecho.")])

    paused = await harness.ask("Abre dos incidencias")
    result = await harness.resume(approved=True)

    assert len(paused["__interrupt__"]) == 1
    assert len(harness.incidents.by_key) == 1
    errors = [m for m in harness.tool_messages(result) if m.status == "error"]
    assert "a la vez" in str(errors[0].content)
