"""Domain model of the simulated core-banking system.

Enum *names* are English (code); enum *values* are what the fictitious core returns and
what the internal policies (in Spanish) refer to, e.g. NOR-008 describes each status.
"""

import json
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

OPERATION_ID_PATTERN = r"^OP-\d{6}$"


class OperationStatus(StrEnum):
    PENDING = "PENDIENTE"
    UNDER_REVIEW = "EN_REVISION"
    SETTLED = "LIQUIDADA"
    REJECTED = "RECHAZADA"
    RETURNED = "DEVUELTA"
    CANCELLED = "CANCELADA"


class OperationType(StrEnum):
    SEPA_TRANSFER = "transferencia_sepa"
    INSTANT_TRANSFER = "transferencia_inmediata"
    INTERNATIONAL_TRANSFER = "transferencia_internacional"
    CASH_DEPOSIT = "ingreso_efectivo"
    CASH_WITHDRAWAL = "retirada_efectivo"
    DIRECT_DEBIT = "recibo_domiciliado"
    LOAN_DISBURSEMENT = "desembolso_prestamo"


class Office(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^\d{4}$")
    name: str
    city: str


class Operation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=OPERATION_ID_PATTERN)
    type: OperationType
    status: OperationStatus
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    office_id: str = Field(pattern=r"^\d{4}$")
    concept: str
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _dates_are_ordered(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError(f"{self.id}: updated_at is earlier than created_at")
        return self


class _OfficesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notice: str
    offices: list[Office]


class _OperationsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notice: str
    operations: list[Operation]


def load_offices(path: Path) -> list[Office]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _OfficesFile.model_validate(raw).offices


def load_operations(path: Path) -> list[Operation]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _OperationsFile.model_validate(raw).operations
