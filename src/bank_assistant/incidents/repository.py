"""Idempotent creation of incidents.

LangGraph re-runs a node from the beginning when it is resumed, and a process can crash
between writing to the database and saving the checkpoint. Either way the same approved
tool call may execute twice, so the write is keyed by an idempotency key derived from the
thread and the tool call: the second execution returns the incident created by the first.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

_INSERT = """
    INSERT INTO incidents (idempotency_key, employee_id, office_id, operation_id, category,
                           description)
    VALUES (%(idempotency_key)s, %(employee_id)s, %(office_id)s, %(operation_id)s,
            %(category)s, %(description)s)
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING incident_number, created_at
"""

_SELECT_BY_KEY = """
    SELECT incident_number, created_at FROM incidents WHERE idempotency_key = %(key)s
"""


@dataclass(frozen=True)
class IncidentRequest:
    idempotency_key: str
    employee_id: str
    office_id: str
    operation_id: str
    category: str
    description: str


@dataclass(frozen=True)
class Incident:
    number: str
    created_at: datetime
    created: bool  # False when the key already existed (a replayed request)


def idempotency_key(thread_id: str, tool_call_id: str) -> str:
    return hashlib.sha256(f"{thread_id}:{tool_call_id}".encode()).hexdigest()


class IncidentRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def create(self, request: IncidentRequest) -> Incident:
        async with self._pool.connection() as conn:
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(_INSERT, request.__dict__)
            row = await cursor.fetchone()
            if row is not None:
                return Incident(row["incident_number"], row["created_at"], created=True)
            await cursor.execute(_SELECT_BY_KEY, {"key": request.idempotency_key})
            existing = await cursor.fetchone()
        if existing is None:  # pragma: no cover - the unique key makes this unreachable
            raise RuntimeError("Incident insert conflicted but no row was found")
        return Incident(existing["incident_number"], existing["created_at"], created=False)
