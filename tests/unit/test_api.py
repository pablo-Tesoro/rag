"""HTTP API tests with fake services: scripted LLM, in-memory checkpointer and data."""

from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from bank_assistant.agent.graph import AgentDeps, build_graph
from bank_assistant.api.app import create_app
from bank_assistant.config import Settings
from bank_assistant.identity import EmployeeDirectory
from bank_assistant.prompts import load_prompt
from bank_assistant.services import Services
from tests.fakes import (
    FakeIncidents,
    FakeSearch,
    RootRunRecorder,
    ScriptedChatModel,
    answer,
    chunk,
    sample_operations,
    tool_call,
)
from tests.helpers import DATA_DIR

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"


class FakeServices:
    def __init__(
        self,
        script: list[AIMessage],
        ready: bool = True,
        llm: bool = True,
        callbacks: list[BaseCallbackHandler] | None = None,
    ) -> None:
        self.llm = ScriptedChatModel(script=script)
        self.incidents = FakeIncidents()
        self.ready = ready
        self.llm_available = llm
        self.callbacks = callbacks or []

    @asynccontextmanager
    async def factory(self, settings: Settings) -> AsyncIterator[Services]:
        prompt = load_prompt(PROMPTS, "agent_system", "v1")
        graph = build_graph(
            AgentDeps(
                llm=self.llm,
                search=FakeSearch([chunk("NOR-005", "2", "5.000 € al día.")]),
                operations=sample_operations(),
                incidents=self.incidents,
                system_prompt=prompt,
            ),
            checkpointer=InMemorySaver(),
        )

        async def readiness() -> dict[str, bool]:
            return {"index_loaded": self.ready, "llm_configured": self.llm_available}

        yield Services(
            settings=settings,
            graph=graph if self.llm_available else None,
            employees=EmployeeDirectory.from_file(DATA_DIR / "employees.json"),
            prompt=prompt,
            readiness=readiness,
            unavailable_reason=None if self.llm_available else "LLM not configured",
            callbacks=self.callbacks,
        )


MakeClient = Callable[..., tuple[TestClient, "FakeServices"]]


@pytest.fixture
def make_client() -> Iterator[MakeClient]:
    clients: list[TestClient] = []

    def make(
        script: list[AIMessage],
        ready: bool = True,
        llm: bool = True,
        callbacks: list[BaseCallbackHandler] | None = None,
    ) -> tuple[TestClient, FakeServices]:
        fake = FakeServices(script, ready, llm, callbacks)
        client = TestClient(create_app(fake.factory))
        client.__enter__()  # runs the lifespan
        clients.append(client)
        return client, fake

    yield make
    for client in clients:
        client.__exit__(None, None, None)


def _incident_script() -> list[AIMessage]:
    return [
        tool_call(
            "abrir_incidencia",
            id_operacion="OP-111111",
            categoria="cargo_duplicado",
            descripcion="Recibo cobrado dos veces",
        ),
        answer("Incidencia registrada."),
    ]


EMP1 = {"X-Employee-Id": "EMP-001"}
EMP2 = {"X-Employee-Id": "EMP-002"}


def test_healthz(make_client: MakeClient) -> None:
    client, _ = make_client([])
    assert client.get("/healthz").json() == {"status": "ok"}


@pytest.mark.parametrize(("ready", "code"), [(True, 200), (False, 503)])
def test_readyz_reports_each_check(make_client: MakeClient, ready: bool, code: int) -> None:
    client, _ = make_client([], ready=ready)
    response = client.get("/readyz")
    assert response.status_code == code
    assert response.json()["checks"]["index_loaded"] is ready


@pytest.mark.parametrize("headers", [{}, {"X-Employee-Id": "EMP-999"}])
def test_chat_requires_a_known_employee(make_client: MakeClient, headers: dict[str, str]) -> None:
    client, _ = make_client([])
    assert client.post("/chat", json={"message": "Hola"}, headers=headers).status_code == 401


def test_chat_returns_a_structured_answer(make_client: MakeClient) -> None:
    client, _ = make_client(
        [
            tool_call("buscar_normativa", consulta="límite inmediata oficina"),
            answer("5.000 € al día.", citas=[("NOR-005", "2")]),
        ]
    )

    body = client.post("/chat", json={"message": "¿Límite?"}, headers=EMP1).json()

    assert body["status"] == "completed"
    assert body["answer"]["citas"] == [{"documento": "NOR-005", "seccion": "2"}]
    assert body["answer"]["sin_evidencia"] is False
    assert body["prompt_version"] == "v1"
    assert len(body["thread_id"]) >= 8


def test_incident_flow_over_http(make_client: MakeClient) -> None:
    client, fake = make_client(_incident_script())

    paused = client.post("/chat", json={"message": "Abre una incidencia"}, headers=EMP1).json()
    assert paused["status"] == "pending_approval"
    assert paused["pending_action"]["args"]["id_operacion"] == "OP-111111"
    assert fake.incidents.by_key == {}

    thread = paused["thread_id"]
    done = client.post(f"/chat/{thread}/approval", json={"approved": True}, headers=EMP1).json()

    assert done["status"] == "completed"
    assert len(fake.incidents.by_key) == 1


def test_a_pending_approval_blocks_new_messages_in_the_thread(make_client: MakeClient) -> None:
    client, _ = make_client(_incident_script())
    thread = client.post("/chat", json={"message": "Abre"}, headers=EMP1).json()["thread_id"]

    response = client.post("/chat", json={"message": "Otra", "thread_id": thread}, headers=EMP1)

    assert response.status_code == 409


def test_other_employees_cannot_continue_or_approve_a_thread(make_client: MakeClient) -> None:
    client, fake = make_client(_incident_script())
    thread = client.post("/chat", json={"message": "Abre"}, headers=EMP1).json()["thread_id"]

    approval = client.post(f"/chat/{thread}/approval", json={"approved": True}, headers=EMP2)
    message = client.post("/chat", json={"message": "Hola", "thread_id": thread}, headers=EMP2)

    assert approval.status_code == 404
    assert message.status_code == 404
    assert fake.incidents.by_key == {}


def test_approval_without_anything_pending_is_a_conflict(make_client: MakeClient) -> None:
    client, _ = make_client([answer("Hola.", sin_evidencia=True)])
    thread = client.post("/chat", json={"message": "Hola"}, headers=EMP1).json()["thread_id"]

    response = client.post(f"/chat/{thread}/approval", json={"approved": True}, headers=EMP1)

    assert response.status_code == 409


def test_unknown_thread_approval_is_not_found(make_client: MakeClient) -> None:
    client, _ = make_client([])
    response = client.post("/chat/unknown-thread-1/approval", json={"approved": True}, headers=EMP1)
    assert response.status_code == 404


def test_without_an_llm_the_app_is_alive_but_not_ready(make_client: MakeClient) -> None:
    client, _ = make_client([], llm=False)

    assert client.get("/healthz").status_code == 200
    ready = client.get("/readyz")
    assert ready.status_code == 503
    assert ready.json()["checks"]["llm_configured"] is False
    chat = client.post("/chat", json={"message": "Hola"}, headers=EMP1)
    assert chat.status_code == 503
    assert "LLM not configured" in chat.json()["detail"]
    assert "validation error" not in chat.json()["detail"]


def test_each_turn_carries_the_tracing_handlers_and_no_raw_employee_id(
    make_client: MakeClient,
) -> None:
    recorder = RootRunRecorder()
    client, _ = make_client([answer("5.000 € al día.")], callbacks=[recorder])

    body = client.post("/chat", json={"message": "¿Límite?"}, headers=EMP1).json()

    [(_, metadata)] = recorder.roots
    assert metadata["thread_id"] == body["thread_id"]
    assert metadata["prompt_version"].startswith("agent_system@v1#")
    assert "EMP-001" not in {str(value) for value in metadata.values()}
