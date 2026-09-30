"""Tool argument schemas and the structured final answer.

These Pydantic models are the contract with the LLM: their titles become tool names, their
docstrings and field descriptions become tool descriptions (in Spanish, the language the
model works in), and every tool call is validated against them before anything runs. A
validation error goes back to the model as a message it can act on.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OPERATION_ID = r"^OP-\d{6}$"
IncidentCategory = Literal[
    "cargo_duplicado", "importe_incorrecto", "abono_no_recibido", "operacion_no_reconocida", "otro"
]


class BuscarNormativa(BaseModel):
    """Busca en la normativa interna de Banco Olvessa y devuelve los fragmentos más
    relevantes, con su documento y sección. Solo devuelve documentos a los que el empleado
    tiene acceso."""

    model_config = ConfigDict(title="buscar_normativa", extra="forbid")

    consulta: str = Field(
        min_length=3,
        max_length=500,
        description="Qué buscar, en lenguaje natural. Incluye códigos exactos si los hay.",
    )
    incluir_obsoletos: bool = Field(
        default=False,
        description="Incluir versiones obsoletas. Solo si el empleado pregunta por una "
        "versión anterior de una política.",
    )


class ConsultarOperacion(BaseModel):
    """Consulta el estado y los datos de una operación del core bancario. Solo devuelve
    operaciones de la oficina del empleado."""

    model_config = ConfigDict(title="consultar_operacion", extra="forbid")

    id_operacion: str = Field(
        pattern=OPERATION_ID, description="Identificador de la operación, p. ej. OP-123456."
    )


class AbrirIncidencia(BaseModel):
    """Propone abrir una incidencia sobre una operación de la oficina del empleado. No se
    registra hasta que el empleado la confirma. Úsala solo si el empleado lo pide
    expresamente."""

    model_config = ConfigDict(title="abrir_incidencia", extra="forbid")

    id_operacion: str = Field(pattern=OPERATION_ID, description="Operación afectada.")
    categoria: IncidentCategory = Field(description="Categoría según el procedimiento.")
    descripcion: str = Field(
        min_length=10,
        max_length=500,
        description="Descripción breve de la anomalía, sin datos personales del cliente.",
    )


class Cita(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documento: str = Field(pattern=r"^NOR-\d{3}$", description="Id del documento, p. ej. NOR-005.")
    seccion: str = Field(pattern=r"^\d+(\.\d+)*$", description="Sección, p. ej. 2 o 3.1.")


class Responder(BaseModel):
    """Entrega la respuesta final al empleado. Llama siempre a esta herramienta para
    terminar."""

    model_config = ConfigDict(title="responder", extra="forbid")

    texto: str = Field(min_length=1, description="Respuesta para el empleado, en español.")
    citas: list[Cita] = Field(
        default_factory=list,
        description="Documentos y secciones de la normativa en los que se basa la respuesta.",
    )
    sin_evidencia: bool = Field(
        description="Verdadero si la normativa recuperada no permite responder la pregunta."
    )


TOOL_SCHEMAS: tuple[type[BaseModel], ...] = (
    BuscarNormativa,
    ConsultarOperacion,
    AbrirIncidencia,
    Responder,
)
READ_TOOLS = frozenset({"buscar_normativa", "consultar_operacion"})
WRITE_TOOL = "abrir_incidencia"
ANSWER_TOOL = "responder"
