"""Writes made during an evaluation go to a sandbox, never to the system of record.

An evaluation run must not open real incidents. The sandbox keeps the contract of
`IncidentRepository` (idempotent by key, same number format) and counts what was written,
which is exactly what the approval checks need. The real write path (unique constraint,
`ON CONFLICT DO NOTHING`, replay after a crash) is covered by the integration tests.
"""

from dataclasses import replace
from datetime import UTC, datetime

from bank_assistant.incidents.repository import Incident, IncidentRequest


class SandboxIncidents:
    def __init__(self) -> None:
        self._by_key: dict[str, Incident] = {}
        self.requests: list[IncidentRequest] = []

    async def create(self, request: IncidentRequest) -> Incident:
        self.requests.append(request)
        existing = self._by_key.get(request.idempotency_key)
        if existing is not None:
            return replace(existing, created=False)
        incident = Incident(f"INC-{len(self._by_key) + 1:06d}", datetime.now(UTC), created=True)
        self._by_key[request.idempotency_key] = incident
        return incident

    @property
    def created(self) -> int:
        """Distinct incidents written (a replayed request does not count twice)."""
        return len(self._by_key)
