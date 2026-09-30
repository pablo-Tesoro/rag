"""End-to-end through HTTP with the real wiring (Postgres index, core banking, incidents and
LangGraph checkpointer) and a scripted LLM instead of Gemini."""

from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from bank_assistant.api.app import create_app
from bank_assistant.config import Settings
from bank_assistant.core_banking.models import load_operations
from bank_assistant.core_banking.repository import CoreBankingRepository
from bank_assistant.db import open_pool
from bank_assistant.ingestion.chunking import ChunkConfig
from bank_assistant.ingestion.pipeline import ingest_corpus
from bank_assistant.services import open_services
from tests.fakes import HashingEmbedder, ScriptedChatModel, answer, tool_call
from tests.helpers import DATA_DIR

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
EMP1 = {"X-Employee-Id": "EMP-001"}


@pytest.fixture(scope="module")
async def loaded_database(schema_conninfo: str) -> str:
    async with await psycopg.AsyncConnection.connect(schema_conninfo) as conn:
        await ingest_corpus(conn, DATA_DIR / "corpus", HashingEmbedder(), ChunkConfig(200, 30))
    pool = await open_pool(schema_conninfo)
    try:
        await CoreBankingRepository(pool).load(
            load_operations(DATA_DIR / "core_banking" / "operations.json")
        )
    finally:
        await pool.close()
    return schema_conninfo


def _client(conninfo: str, llm: ScriptedChatModel) -> TestClient:
    settings = Settings(database_url=conninfo, data_dir=DATA_DIR, prompts_dir=PROMPTS)
    app = create_app(lambda _: open_services(settings, llm=llm, embedder=HashingEmbedder()))
    return TestClient(app)


def test_ready_answer_and_approval_survive_across_requests(loaded_database: str) -> None:
    llm = ScriptedChatModel(
        script=[
            tool_call("buscar_normativa", consulta="límite diario transferencia inmediata oficina"),
            answer("5.000 € por cliente y día.", citas=[("NOR-005", "2")]),
            tool_call(
                "abrir_incidencia",
                id_operacion="OP-582214",
                categoria="cargo_duplicado",
                descripcion="Recibo cobrado dos veces",
            ),
            answer("Incidencia registrada."),
        ]
    )
    with _client(loaded_database, llm) as client:
        assert client.get("/readyz").json()["ready"] is True

        first = client.post("/chat", json={"message": "¿Límite inmediata?"}, headers=EMP1).json()
        assert first["status"] == "completed"
        assert first["answer"]["citas"] == [{"documento": "NOR-005", "seccion": "2"}]

        thread = first["thread_id"]
        paused = client.post(
            "/chat", json={"message": "Abre una incidencia", "thread_id": thread}, headers=EMP1
        ).json()
        assert paused["status"] == "pending_approval"

    # A new app instance (think: a restart) resumes the same thread from Postgres.
    with _client(loaded_database, llm) as client:
        done = client.post(f"/chat/{thread}/approval", json={"approved": True}, headers=EMP1).json()
        assert done["status"] == "completed"

    with psycopg.connect(loaded_database) as conn:
        row = conn.execute(
            "SELECT count(*), max(operation_id) FROM incidents WHERE employee_id = 'EMP-001'"
        ).fetchone()
    assert row == (1, "OP-582214")
