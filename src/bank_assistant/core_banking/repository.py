"""Read access to the simulated core banking, always scoped to the employee's office."""

from collections.abc import Iterable

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from bank_assistant.core_banking.models import Operation

_SELECT_OPERATION = """
    SELECT operation_id AS id, type, status, amount, currency, office_id, concept,
           created_at, updated_at
    FROM core_operations
    WHERE operation_id = %(operation_id)s AND office_id = %(office_id)s
"""

_UPSERT_OPERATION = """
    INSERT INTO core_operations (operation_id, type, status, amount, currency, office_id,
                                 concept, created_at, updated_at)
    VALUES (%(id)s, %(type)s, %(status)s, %(amount)s, %(currency)s, %(office_id)s,
            %(concept)s, %(created_at)s, %(updated_at)s)
    ON CONFLICT (operation_id) DO UPDATE SET
        type = EXCLUDED.type, status = EXCLUDED.status, amount = EXCLUDED.amount,
        currency = EXCLUDED.currency, office_id = EXCLUDED.office_id,
        concept = EXCLUDED.concept, created_at = EXCLUDED.created_at,
        updated_at = EXCLUDED.updated_at
"""


class CoreBankingRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def get_operation(self, operation_id: str, *, office_id: str) -> Operation | None:
        """The operation if it exists *and* belongs to `office_id`; None otherwise.

        Both cases return None on purpose: callers cannot tell "does not exist" from
        "belongs to another office", so the API is not an existence oracle.
        """
        async with self._pool.connection() as conn:
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                _SELECT_OPERATION, {"operation_id": operation_id, "office_id": office_id}
            )
            row = await cursor.fetchone()
        return Operation.model_validate(row) if row else None

    async def load(self, operations: Iterable[Operation]) -> int:
        """Upsert the fictitious operations (idempotent)."""
        rows = [op.model_dump() for op in operations]
        async with self._pool.connection() as conn, conn.cursor() as cursor:
            await cursor.executemany(_UPSERT_OPERATION, rows)
        return len(rows)
