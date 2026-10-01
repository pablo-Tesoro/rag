"""The agent as an explicit LangGraph StateGraph.

    START → agent ─┬─ read tools ──────────→ tools ─┬─ incident proposed → approval → agent
                   │                                 └──────────────────────────────→ agent
                   └─ `responder` / plain text / budget exhausted → finalize ─┬→ END
                                                                             └→ agent (one fix)

- agent: the LLM with the four tools bound. It decides; it never executes anything.
- tools: runs read-only tools with argument validation, a per-tool timeout and loop
  detection. Errors come back as tool messages the model can act on.
- approval: the only write. Validates, checks the operation belongs to the employee's office,
  then pauses with `interrupt()` until a human approves or rejects. The write happens after
  the interrupt and is idempotent, because a resumed node runs again from the start.
- finalize: validates the structured answer. Citations must point to chunks actually
  retrieved in this thread; an invalid answer is sent back to the model once.
"""

import asyncio
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolCall, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from pydantic import ValidationError

from bank_assistant.agent import tools as tool_impl
from bank_assistant.agent.guards import (
    answer_corrections_in_turn,
    call_signature,
    citation_is_supported,
    tool_calls_in_turn,
    working_calls_in_turn,
)
from bank_assistant.agent.schemas import (
    ANSWER_TOOL,
    TOOL_SCHEMAS,
    WRITE_TOOL,
    AbrirIncidencia,
    BuscarNormativa,
    ConsultarOperacion,
    Responder,
)
from bank_assistant.agent.state import AgentContext, AgentState, RetrievedRef
from bank_assistant.agent.tools import (
    DocumentSearch,
    IncidentWriter,
    OperationsReader,
    ToolOutcome,
    not_found_message,
)
from bank_assistant.incidents.repository import IncidentRequest, idempotency_key
from bank_assistant.prompts import Prompt

log = logging.getLogger(__name__)

AGENT: Final = "agent"
TOOLS: Final = "tools"
APPROVAL: Final = "approval"
FINALIZE: Final = "finalize"

# Hints appended to validation errors so the model can fix the call by itself.
_FIELD_HINTS = {
    "id_operacion": "formato OP- seguido de 6 dígitos, p. ej. OP-123456",
    "categoria": "cargo_duplicado, importe_incorrecto, abono_no_recibido, "
    "operacion_no_reconocida u otro",
    "consulta": "texto de 3 a 500 caracteres",
    "descripcion": "texto de 10 a 500 caracteres, sin datos personales",
}


@dataclass(frozen=True)
class AgentDeps:
    llm: BaseChatModel
    search: DocumentSearch
    operations: OperationsReader
    incidents: IncidentWriter
    system_prompt: Prompt
    top_k: int = 5
    tool_timeout_s: float = 10.0
    max_tool_calls_per_turn: int = 8


def describe_validation_error(tool: str, error: ValidationError) -> str:
    problems = []
    for item in error.errors():
        field = ".".join(str(part) for part in item["loc"]) or "argumentos"
        hint = _FIELD_HINTS.get(field)
        problems.append(f"{field}: {item['msg']}" + (f" ({hint})" if hint else ""))
    return f"Error: argumentos no válidos para {tool}: " + "; ".join(problems)


def _tool_message(call: ToolCall, outcome: ToolOutcome) -> ToolMessage:
    return ToolMessage(
        outcome.content,
        tool_call_id=call["id"] or "",
        name=call["name"],
        status="error" if outcome.is_error else "success",
    )


def _last_ai_message(messages: list[AnyMessage]) -> AIMessage:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message
    raise ValueError("No AI message in the conversation")


def _fallback_answer(texto: str, terminacion: str) -> dict[str, Any]:
    return {"texto": texto, "citas": [], "sin_evidencia": True, "terminacion": terminacion}


def build_graph(
    deps: AgentDeps, checkpointer: BaseCheckpointSaver[Any] | None = None
) -> CompiledStateGraph[AgentState, AgentContext, AgentState, AgentState]:
    model = deps.llm.bind_tools(list(TOOL_SCHEMAS))

    # ------------------------------------------------------------------ agent
    async def agent(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
        employee = runtime.context.employee
        system = SystemMessage(
            f"{deps.system_prompt.text}\n\n# Contexto\n"
            f"El empleado trabaja en la oficina {employee.office_id} ({employee.role})."
        )
        response = await model.ainvoke([system, *state["messages"]])
        return {"messages": [response]}

    def route_after_agent(state: AgentState) -> Literal["tools", "finalize"]:
        last = state["messages"][-1]
        if not isinstance(last, AIMessage) or not last.tool_calls:
            return FINALIZE
        if any(call["name"] == ANSWER_TOOL for call in last.tool_calls):
            return FINALIZE
        if working_calls_in_turn(state["messages"]) > deps.max_tool_calls_per_turn:
            return FINALIZE
        return TOOLS

    # ------------------------------------------------------------------ tools
    async def run_read_tool(call: ToolCall, ctx: AgentContext) -> ToolOutcome:
        name, raw_args = call["name"], call["args"]
        # Validate first: a coroutine is only created for a well-formed call.
        pending: Awaitable[ToolOutcome]
        try:
            if name == "buscar_normativa":
                search_args = BuscarNormativa.model_validate(raw_args)
                pending = tool_impl.buscar_normativa(search_args, ctx, deps.search, deps.top_k)
            elif name == "consultar_operacion":
                lookup_args = ConsultarOperacion.model_validate(raw_args)
                pending = tool_impl.consultar_operacion(lookup_args, ctx, deps.operations)
            else:
                return ToolOutcome(
                    f"Error: la herramienta '{name}' no existe. Usa buscar_normativa, "
                    "consultar_operacion, abrir_incidencia o responder.",
                    is_error=True,
                )
        except ValidationError as error:
            return ToolOutcome(describe_validation_error(name, error), is_error=True)

        try:
            return await asyncio.wait_for(pending, timeout=deps.tool_timeout_s)
        except TimeoutError:
            return ToolOutcome(
                f"Error: {name} no respondió en {deps.tool_timeout_s:.0f} s. Inténtalo de nuevo "
                "o responde con la información que ya tengas.",
                is_error=True,
            )
        except Exception:
            log.exception("tool.failed", extra={"fields": {"tool": name}})
            return ToolOutcome(
                f"Error: {name} ha fallado por un problema interno. Indica al empleado que no "
                "puedes consultarlo en este momento.",
                is_error=True,
            )

    async def tools(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
        last = _last_ai_message(state["messages"])
        seen = {
            call_signature(c["name"], c["args"]) for c in tool_calls_in_turn(state["messages"][:-1])
        }
        tasks: list[Awaitable[ToolOutcome]] = []
        calls: list[ToolCall] = []
        for call in last.tool_calls:
            if call["name"] in (WRITE_TOOL, ANSWER_TOOL):
                continue
            signature = call_signature(call["name"], call["args"])
            calls.append(call)
            if signature in seen:
                tasks.append(_repeated_call(call))
            else:
                seen.add(signature)
                tasks.append(run_read_tool(call, runtime.context))
        outcomes = await asyncio.gather(*tasks)

        retrieved: dict[str, RetrievedRef] = {}
        for outcome in outcomes:
            retrieved.update(outcome.retrieved)
        messages = [_tool_message(call, o) for call, o in zip(calls, outcomes, strict=True)]
        return {"messages": messages, "retrieved": retrieved}

    def route_after_tools(state: AgentState) -> Literal["approval", "agent"]:
        last_ai = _last_ai_message(state["messages"])
        return APPROVAL if any(c["name"] == WRITE_TOOL for c in last_ai.tool_calls) else AGENT

    # --------------------------------------------------------------- approval
    async def approval(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
        # Everything before interrupt() runs again on resume, so it must be read-only.
        ctx = runtime.context
        last = _last_ai_message(state["messages"])
        proposals = [c for c in last.tool_calls if c["name"] == WRITE_TOOL]
        call, extra = proposals[0], proposals[1:]
        messages = [
            _tool_message(
                c, ToolOutcome("Error: solo se puede proponer una incidencia a la vez.", True)
            )
            for c in extra
        ]

        earlier = {
            call_signature(c["name"], c["args"])
            for c in tool_calls_in_turn(state["messages"][:-1])
            if c["name"] == WRITE_TOOL
        }
        if call_signature(call["name"], call["args"]) in earlier:
            outcome = ToolOutcome(
                "Error: esta incidencia ya se propuso en esta consulta. No la repitas.", True
            )
            return {"messages": [_tool_message(call, outcome), *messages]}
        try:
            args = AbrirIncidencia.model_validate(call["args"])
        except ValidationError as error:
            outcome = ToolOutcome(describe_validation_error(WRITE_TOOL, error), True)
            return {"messages": [_tool_message(call, outcome), *messages]}

        operation = await deps.operations.get_operation(
            args.id_operacion, office_id=ctx.employee.office_id
        )
        if operation is None:
            outcome = ToolOutcome(
                not_found_message(args.id_operacion) + " No se puede abrir la incidencia.", True
            )
            return {"messages": [_tool_message(call, outcome), *messages]}

        decision = interrupt(
            {
                "type": "approval_request",
                "action": WRITE_TOOL,
                "tool_call_id": call["id"],
                "args": args.model_dump(),
                "operation": {
                    "id": operation.id,
                    "tipo": operation.type.value,
                    "estado": operation.status.value,
                    "importe": str(Decimal(operation.amount)),
                    "divisa": operation.currency,
                },
            }
        )
        approved = isinstance(decision, dict) and decision.get("approved") is True
        if not approved:
            # Explicit about who decided and what to say: with a vaguer text the real model
            # answered as if confirmation were still pending and asked for it again.
            outcome = ToolOutcome(
                "El empleado ha rechazado la incidencia que propusiste: ha decidido no abrirla "
                "y no se ha registrado. Díselo hablándole de tú y sin pedirle otra "
                "confirmación. No vuelvas a proponerla salvo que el empleado lo pida de nuevo."
            )
            return {"messages": [_tool_message(call, outcome), *messages]}

        thread_id = runtime.execution_info.thread_id if runtime.execution_info else None
        if not thread_id:
            raise RuntimeError("Approvals need a checkpointer and a thread_id")
        incident = await deps.incidents.create(
            IncidentRequest(
                idempotency_key=idempotency_key(thread_id, call["id"] or ""),
                employee_id=ctx.employee.id,
                office_id=ctx.employee.office_id,
                operation_id=args.id_operacion,
                category=args.categoria,
                description=args.descripcion,
            )
        )
        log.info(
            "incident.created",
            extra={"fields": {"incident": incident.number, "replayed": not incident.created}},
        )
        outcome = ToolOutcome(
            f"Incidencia {incident.number} registrada sobre {args.id_operacion} "
            f"(categoría {args.categoria}). Comunica el número al empleado."
        )
        return {"messages": [_tool_message(call, outcome), *messages]}

    # --------------------------------------------------------------- finalize
    async def finalize(state: AgentState) -> dict[str, Any]:
        history = state["messages"]
        last = history[-1]
        if not isinstance(last, AIMessage):
            return {"final_answer": _fallback_answer("No he podido responder.", "sin_respuesta")}

        answer_call = next((c for c in last.tool_calls if c["name"] == ANSWER_TOOL), None)
        if answer_call is None and last.tool_calls:
            # Tool budget exhausted: close every pending call and stop.
            closing = [
                _tool_message(c, ToolOutcome("No ejecutada: límite de llamadas alcanzado.", True))
                for c in last.tool_calls
            ]
            return {
                "messages": closing,
                "final_answer": _fallback_answer(
                    "No he podido completar la consulta dentro del límite de pasos. "
                    "Prueba a formularla de forma más concreta.",
                    "limite_herramientas",
                ),
            }
        if answer_call is None:
            # The model answered in plain text instead of calling `responder`.
            text = last.text.strip()
            if not text:
                fallback = _fallback_answer("No he podido responder.", "sin_respuesta")
                return {"final_answer": fallback}
            return {
                "final_answer": {
                    "texto": text,
                    "citas": [],
                    "sin_evidencia": False,
                    "terminacion": "texto_libre",
                }
            }

        ignored = [
            _tool_message(c, ToolOutcome("Ignorada: ya se ha entregado la respuesta final."))
            for c in last.tool_calls
            if c is not answer_call
        ]
        can_fix = answer_corrections_in_turn(history) < 1
        try:
            answer = Responder.model_validate(answer_call["args"])
        except ValidationError as error:
            if can_fix:
                outcome = ToolOutcome(describe_validation_error(ANSWER_TOOL, error), True)
                return {"messages": [*ignored, _tool_message(answer_call, outcome)]}
            rejected = ToolOutcome("Respuesta no válida.", True)
            return {
                "messages": [*ignored, _tool_message(answer_call, rejected)],
                "final_answer": _fallback_answer("No he podido responder.", "respuesta_invalida"),
            }

        # Citations are checked the same way whether or not the answer abstains: an
        # abstention may cite the public section that refers to an inaccessible document.
        retrieved = state.get("retrieved") or {}
        unsupported = [c for c in answer.citas if not citation_is_supported(c, retrieved)]
        if unsupported and can_fix:
            listed = ", ".join(f"{c.documento} §{c.seccion}" for c in unsupported)
            outcome = ToolOutcome(
                f"Error: estas citas no están entre los documentos recuperados: {listed}. "
                "Cita solo documentos y secciones de los resultados de buscar_normativa, o "
                "busca de nuevo antes de responder.",
                True,
            )
            return {"messages": [*ignored, _tool_message(answer_call, outcome)]}

        citas = [c for c in answer.citas if c not in unsupported]
        final = {
            "texto": answer.texto,
            "citas": [c.model_dump() for c in citas],
            "sin_evidencia": answer.sin_evidencia,
            "terminacion": "respuesta",
        }
        if unsupported:
            final["citas_descartadas"] = [c.model_dump() for c in unsupported]
        delivered = _tool_message(answer_call, ToolOutcome("Respuesta entregada."))
        return {"messages": [*ignored, delivered], "final_answer": final}

    def route_after_finalize(state: AgentState) -> str:
        return END if state.get("final_answer") is not None else AGENT

    builder = StateGraph(AgentState, context_schema=AgentContext)
    builder.add_node(AGENT, agent)
    builder.add_node(TOOLS, tools)
    builder.add_node(APPROVAL, approval)
    builder.add_node(FINALIZE, finalize)
    builder.add_edge(START, AGENT)
    builder.add_conditional_edges(AGENT, route_after_agent, [TOOLS, FINALIZE])
    builder.add_conditional_edges(TOOLS, route_after_tools, [APPROVAL, AGENT])
    builder.add_edge(APPROVAL, AGENT)
    builder.add_conditional_edges(FINALIZE, route_after_finalize, [AGENT, END])
    return builder.compile(checkpointer=checkpointer)


async def _repeated_call(call: ToolCall) -> ToolOutcome:
    return ToolOutcome(
        f"Error: ya has llamado a {call['name']} con estos mismos argumentos en esta consulta. "
        "Usa el resultado anterior, cambia la consulta o responde.",
        is_error=True,
    )
