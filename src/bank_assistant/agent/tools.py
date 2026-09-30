"""Tool implementations and the formatting of their results for the model.

Tools receive the employee from the invocation context (never from the model), and their
dependencies behind small protocols so tests can swap them for in-memory fakes.

Retrieved documents and operations are wrapped in XML-like tags with their content
escaped: the system prompt tells the model that anything inside those tags is data, and
escaping stops a document from closing the tag and "escaping" into the instructions.
"""

import html
from dataclasses import dataclass, field
from typing import Protocol

from bank_assistant.agent.schemas import BuscarNormativa, ConsultarOperacion
from bank_assistant.agent.state import AgentContext, RetrievedRef
from bank_assistant.core_banking.models import Operation
from bank_assistant.incidents.repository import Incident, IncidentRequest
from bank_assistant.retrieval import RetrievalMode
from bank_assistant.retrieval.retriever import RetrievedChunk


class DocumentSearch(Protocol):
    async def search(
        self,
        query: str,
        *,
        groups: frozenset[str],
        mode: RetrievalMode,
        k: int = 5,
        include_obsolete: bool = False,
    ) -> list[RetrievedChunk]: ...


class OperationsReader(Protocol):
    async def get_operation(self, operation_id: str, *, office_id: str) -> Operation | None: ...


class IncidentWriter(Protocol):
    async def create(self, request: IncidentRequest) -> Incident: ...


@dataclass(frozen=True)
class ToolOutcome:
    content: str
    is_error: bool = False
    retrieved: dict[str, RetrievedRef] = field(default_factory=dict)


def escape(text: str) -> str:
    return html.escape(text, quote=True)


def format_chunks(query: str, chunks: list[RetrievedChunk]) -> str:
    parts = [f'<resultados consulta="{escape(query)}">']
    for chunk in chunks:
        parts.append(
            f'<documento id="{chunk.doc_id}" seccion="{chunk.section}" '
            f'titulo="{escape(chunk.title)}" version="{chunk.version}" estado="{chunk.status}" '
            f'ruta="{escape(chunk.heading_path)}">\n{escape(chunk.content)}\n</documento>'
        )
    parts.append("</resultados>")
    return "\n".join(parts)


def format_operation(operation: Operation) -> str:
    return (
        f'<operacion id="{operation.id}">\n'
        f"tipo: {operation.type.value}\n"
        f"estado: {operation.status.value}\n"
        f"importe: {operation.amount} {operation.currency}\n"
        f"concepto: {escape(operation.concept)}\n"
        f"fecha_alta: {operation.created_at.isoformat()}\n"
        f"ultima_actualizacion: {operation.updated_at.isoformat()}\n"
        "</operacion>"
    )


def not_found_message(operation_id: str) -> str:
    # Identical for "does not exist" and "belongs to another office" (no existence oracle).
    return (
        f"No se ha encontrado ninguna operación {operation_id} entre las operaciones "
        "accesibles para la oficina del empleado."
    )


async def buscar_normativa(
    args: BuscarNormativa, ctx: AgentContext, search: DocumentSearch, top_k: int
) -> ToolOutcome:
    chunks = await search.search(
        args.consulta,
        groups=ctx.employee.groups,
        mode=ctx.retrieval_mode,
        k=top_k,
        include_obsolete=args.incluir_obsoletos,
    )
    if not chunks:
        return ToolOutcome(
            "No se han encontrado documentos para esta consulta. Prueba otra formulación o, "
            "si no hay evidencia, indícalo con sin_evidencia."
        )
    retrieved: dict[str, RetrievedRef] = {
        c.chunk_id: {"doc_id": c.doc_id, "section": c.section, "title": c.title, "status": c.status}
        for c in chunks
    }
    return ToolOutcome(format_chunks(args.consulta, chunks), retrieved=retrieved)


async def consultar_operacion(
    args: ConsultarOperacion, ctx: AgentContext, operations: OperationsReader
) -> ToolOutcome:
    operation = await operations.get_operation(args.id_operacion, office_id=ctx.employee.office_id)
    if operation is None:
        return ToolOutcome(not_found_message(args.id_operacion))
    return ToolOutcome(format_operation(operation))
