"""Traces: opt-in, and nothing identifying leaves the process unmasked.

The end-to-end test points the LangSmith client at a local fake endpoint and inspects the
bytes that would have been uploaded: no network, no API key needed.
"""

import threading
import uuid
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tracers import LangChainTracer
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr

from bank_assistant.agent.graph import AgentDeps, build_graph
from bank_assistant.agent.state import AgentContext
from bank_assistant.config import Settings
from bank_assistant.identity import Employee
from bank_assistant.logs import pseudonymize
from bank_assistant.prompts import load_prompt
from bank_assistant.retrieval import RetrievalMode
from bank_assistant.tracing import build_tracer, mask_text
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
KEY = "test-pseudonym-key"


# ----------------------------------------------------------------------------- masking


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("DNI 12345678Z", "DNI [DNI]"),
        ("NIE X1234567L", "NIE [NIE]"),
        ("IBAN ES91 2100 0418 4502 0005 1332", "IBAN [IBAN]"),
        ("IBAN ES9121000418450200051332", "IBAN [IBAN]"),
        ("correo cliente.prueba@example.com", "correo [EMAIL]"),
        ("tel. 612 345 678", "tel. [TELEFONO]"),
        ("tel. +34 912345678", "tel. [TELEFONO]"),
    ],
)
def test_customer_identifiers_are_replaced(text: str, masked: str) -> None:
    assert mask_text(text, KEY) == masked


def test_employee_ids_become_the_same_pseudonym_as_in_the_logs() -> None:
    masked = mask_text("Pregunta de EMP-001", KEY)

    assert masked == f"Pregunta de emp_{pseudonymize('EMP-001', KEY)}"


@pytest.mark.parametrize(
    "text",
    [
        "OP-104233 en EN_REVISION por 1.850,00 €",
        "Incidencia INC-000001, categoría cargo_duplicado",
        "CTA-NOM-02, PRS-CONS-36, TRF-INT-USD y HIP-FIJ-30",
        "Hasta 200.000 € o 1.000.000 €; 600 puntos de scoring",
        "De lunes a viernes, de 8:30 a 14:00; alta 2025-09-24T10:12:00+02:00",
    ],
)
def test_business_data_is_left_alone(text: str) -> None:
    assert mask_text(text, KEY) == text


# ------------------------------------------------------- a fake LangSmith endpoint


class _Recorder(BaseHTTPRequestHandler):
    # Shared by every handler instance; the fixture resets it for each test.
    requests: ClassVar[list[tuple[str, str, dict[str, str], bytes]]] = []

    def _record(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.requests.append((self.command, self.path, dict(self.headers), body))
        self.send_response(200 if self.command == "GET" else 202)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    do_GET = do_POST = do_PATCH = _record

    def log_message(self, *args: Any) -> None:  # keep test output clean
        pass


@pytest.fixture
def fake_langsmith() -> Iterator[tuple[str, list[tuple[str, str, dict[str, str], bytes]]]]:
    _Recorder.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", _Recorder.requests
    server.shutdown()


# ------------------------------------------------------------------------- the tracer


def test_tracing_is_off_by_default() -> None:
    assert build_tracer(Settings()) is None


def test_switching_tracing_on_without_a_key_disables_it_instead_of_failing() -> None:
    settings = Settings(trace_to_langsmith=True, langsmith_api_key=SecretStr(""))

    assert build_tracer(settings) is None


def test_a_configured_tracer_uses_the_project_and_endpoint(
    fake_langsmith: tuple[str, list[tuple[str, str, dict[str, str], bytes]]],
) -> None:
    endpoint, _ = fake_langsmith
    settings = Settings(
        trace_to_langsmith=True,
        langsmith_api_key=SecretStr("lsv2-test"),
        langsmith_endpoint=endpoint,
    )

    tracer = build_tracer(settings, project="banco-olvessa-evals")

    assert isinstance(tracer, LangChainTracer)
    assert tracer.project_name == "banco-olvessa-evals"
    assert tracer.client.api_url == endpoint
    # The client probes the endpoint once in the background: let it happen while it is up.
    assert tracer.client.info is not None


# ----------------------------------------------------- what actually leaves the process


async def test_a_traced_turn_uploads_masked_identifiers_only(
    fake_langsmith: tuple[str, list[tuple[str, str, dict[str, str], bytes]]],
) -> None:
    endpoint, requests = fake_langsmith
    settings = Settings(
        trace_to_langsmith=True,
        langsmith_api_key=SecretStr("lsv2-test"),
        langsmith_endpoint=endpoint,
        log_pseudonym_key=SecretStr(KEY),
    )
    tracer = build_tracer(settings)
    assert tracer is not None
    employee = Employee(
        id="EMP-001", role="Gestión comercial", office_id="0101", groups=frozenset({"todos"})
    )
    llm = ScriptedChatModel(
        script=[
            tool_call("buscar_normativa", consulta="límite para el cliente 12345678Z"),
            answer("Para 12345678Z: 5.000 € por día.", citas=[("NOR-005", "2")]),
        ]
    )
    graph = build_graph(
        AgentDeps(
            llm=llm,
            search=FakeSearch([chunk("NOR-005", "2", "Límite en oficina: 5.000 €.")]),
            operations=sample_operations(),
            incidents=FakeIncidents(),
            system_prompt=load_prompt(PROMPTS, "agent_system", "v1"),
        ),
        checkpointer=InMemorySaver(),
    )

    await graph.ainvoke(
        {
            "messages": [HumanMessage("Soy EMP-001 y el cliente 12345678Z pregunta su límite")],
            "employee_id": "EMP-001",
            "retrieved": {},
            "final_answer": None,
        },
        {"configurable": {"thread_id": uuid.uuid4().hex}, "callbacks": [tracer]},
        context=AgentContext(employee=employee, retrieval_mode=RetrievalMode.HYBRID),
    )
    tracer.wait_for_futures()

    uploads = [r for r in requests if r[0] == "POST"]
    sent = b"".join(body for *_, body in uploads)
    assert uploads, "nothing was sent to the tracing endpoint"
    assert uploads[0][2].get("x-api-key") == "lsv2-test"
    assert b"EMP-001" not in sent
    assert b"12345678Z" not in sent
    assert f"emp_{pseudonymize('EMP-001', KEY)}".encode() in sent
    assert b"[DNI]" in sent
    assert "5.000 €".encode() in sent  # the content itself is traced: that is the point
