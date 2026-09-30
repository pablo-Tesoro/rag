import pytest
from psycopg_pool import AsyncConnectionPool

from bank_assistant.core_banking.models import load_operations
from bank_assistant.core_banking.repository import CoreBankingRepository
from bank_assistant.incidents.repository import IncidentRepository, IncidentRequest, idempotency_key
from tests.helpers import DATA_DIR


@pytest.fixture(scope="module")
async def core(pool: AsyncConnectionPool) -> CoreBankingRepository:
    repository = CoreBankingRepository(pool)
    await repository.load(load_operations(DATA_DIR / "core_banking" / "operations.json"))
    return repository


async def test_operations_are_only_visible_to_their_own_office(core: CoreBankingRepository) -> None:
    own = await core.get_operation("OP-104233", office_id="0101")
    other = await core.get_operation("OP-477120", office_id="0101")  # belongs to 0412

    assert own is not None and own.status.value == "EN_REVISION"
    assert other is None
    assert await core.get_operation("OP-999999", office_id="0101") is None


async def test_loading_operations_twice_is_idempotent(
    core: CoreBankingRepository, pool: AsyncConnectionPool
) -> None:
    await core.load(load_operations(DATA_DIR / "core_banking" / "operations.json"))
    async with pool.connection() as conn:
        cursor = await conn.execute("SELECT count(*) FROM core_operations")
        row = await cursor.fetchone()
    assert row is not None and row[0] == 50


def _request(key: str) -> IncidentRequest:
    return IncidentRequest(
        idempotency_key=key,
        employee_id="EMP-001",
        office_id="0101",
        operation_id="OP-582214",
        category="cargo_duplicado",
        description="Recibo cobrado dos veces",
    )


async def test_the_same_idempotency_key_creates_a_single_incident(
    pool: AsyncConnectionPool,
) -> None:
    repository = IncidentRepository(pool)
    key = idempotency_key("thread-1", "call-1")

    first = await repository.create(_request(key))
    replay = await repository.create(_request(key))
    other = await repository.create(_request(idempotency_key("thread-1", "call-2")))

    assert first.created and not replay.created
    assert replay.number == first.number
    assert other.number != first.number
    assert first.number.startswith("INC-")
