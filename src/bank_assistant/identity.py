"""Simulated employees.

There is no real authentication: the API receives the employee id in a header. What we do
simulate faithfully is *delegated* authorisation: every downstream query runs with the
employee's identity (office and groups), as it would with an on-behalf-of token, and the
LLM never gets to choose that identity.
"""

import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class Employee(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^EMP-\d{3}$")
    role: str
    office_id: str = Field(pattern=r"^\d{4}$")
    groups: frozenset[str] = Field(min_length=1)


class _EmployeesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notice: str
    employees: list[Employee]


class EmployeeDirectory:
    def __init__(self, employees: Iterable[Employee]) -> None:
        self._by_id: dict[str, Employee] = {}
        for employee in employees:
            if employee.id in self._by_id:
                raise ValueError(f"Duplicate employee id: {employee.id}")
            self._by_id[employee.id] = employee

    @classmethod
    def from_file(cls, path: Path) -> "EmployeeDirectory":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(_EmployeesFile.model_validate(raw).employees)

    def get(self, employee_id: str) -> Employee | None:
        return self._by_id.get(employee_id)

    def __iter__(self) -> Iterator[Employee]:
        return iter(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)
