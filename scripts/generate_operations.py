"""Generate the fictitious core-banking operations (data/core_banking/operations.json).

A handful of operations are curated because evaluation cases refer to them by id; the rest
are pseudo-random with a fixed seed, so the output is identical on every run.
"""

import json
import random
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from bank_assistant.core_banking.models import Operation, OperationStatus, OperationType

OUTPUT = Path(__file__).resolve().parents[1] / "data" / "core_banking" / "operations.json"
SEED = 20250930
TOTAL = 50
TZ = ZoneInfo("Europe/Madrid")
NOTICE = (
    "Operaciones ficticias de Banco Olvessa (entidad inventada), creadas con fines de "
    "demostración. Sin datos personales."
)
# Referenced by the eval dataset as an operation that does not exist.
RESERVED_IDS = {"OP-999999"}


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


def _op(
    op_id: str,
    op_type: OperationType,
    status: OperationStatus,
    amount: str,
    office_id: str,
    concept: str,
    created: str,
    updated: str,
    currency: str = "EUR",
) -> Operation:
    return Operation(
        id=op_id,
        type=op_type,
        status=status,
        amount=Decimal(amount),
        currency=currency,
        office_id=office_id,
        concept=concept,
        created_at=_at(created),
        updated_at=_at(updated),
    )


# Curated operations used by evals/dataset.jsonl. Keep ids stable.
CURATED = [
    _op(
        "OP-104233",
        OperationType.INSTANT_TRANSFER,
        OperationStatus.UNDER_REVIEW,
        "1850.00",
        "0101",
        "Transferencia a beneficiario nuevo",
        "2025-09-24T10:12:00",
        "2025-09-24T10:12:40",
    ),
    _op(
        "OP-582214",
        OperationType.DIRECT_DEBIT,
        OperationStatus.SETTLED,
        "45.20",
        "0101",
        "Recibo suministro eléctrico",
        "2025-09-15T06:00:00",
        "2025-09-15T06:05:00",
    ),
    _op(
        "OP-731904",
        OperationType.SEPA_TRANSFER,
        OperationStatus.SETTLED,
        "250.00",
        "0101",
        "Transferencia periódica",
        "2025-09-01T09:00:00",
        "2025-09-02T08:00:00",
    ),
    _op(
        "OP-208871",
        OperationType.SEPA_TRANSFER,
        OperationStatus.SETTLED,
        "12400.00",
        "0205",
        "Pago a proveedor",
        "2025-09-22T11:30:00",
        "2025-09-23T08:00:00",
    ),
    _op(
        "OP-639015",
        OperationType.INTERNATIONAL_TRANSFER,
        OperationStatus.SETTLED,
        "3200.00",
        "0205",
        "Transferencia internacional recibida",
        "2025-09-18T15:20:00",
        "2025-09-22T10:45:00",
        currency="USD",
    ),
    _op(
        "OP-310552",
        OperationType.DIRECT_DEBIT,
        OperationStatus.RETURNED,
        "89.90",
        "0310",
        "Recibo seguro de hogar",
        "2025-09-05T06:00:00",
        "2025-09-08T12:30:00",
    ),
    _op(
        "OP-477120",
        OperationType.SEPA_TRANSFER,
        OperationStatus.UNDER_REVIEW,
        "7300.00",
        "0412",
        "Pago de señal de compraventa",
        "2025-09-26T12:05:00",
        "2025-09-26T12:06:00",
    ),
]

OFFICE_WEIGHTS = {"0101": 14, "0205": 12, "0310": 12, "0412": 12}
TYPE_PROFILE: dict[OperationType, tuple[tuple[int, int], list[str]]] = {
    OperationType.SEPA_TRANSFER: (
        (50, 9000),
        ["Pago de alquiler", "Pago a proveedor", "Transferencia entre cuentas", "Pago de factura"],
    ),
    OperationType.INSTANT_TRANSFER: (
        (20, 1900),
        ["Pago entre particulares", "Envío urgente", "Reembolso de gastos"],
    ),
    OperationType.INTERNATIONAL_TRANSFER: (
        (300, 15000),
        ["Pago a proveedor extranjero", "Transferencia internacional recibida"],
    ),
    OperationType.CASH_DEPOSIT: ((100, 9500), ["Ingreso en ventanilla", "Ingreso de recaudación"]),
    OperationType.CASH_WITHDRAWAL: ((50, 3000), ["Reintegro en ventanilla"]),
    OperationType.DIRECT_DEBIT: (
        (10, 400),
        ["Recibo de telefonía", "Recibo de gimnasio", "Recibo comunidad de propietarios"],
    ),
    OperationType.LOAN_DISBURSEMENT: (
        (3000, 30000),
        ["Desembolso préstamo consumo", "Desembolso préstamo coche"],
    ),
}
STATUS_WEIGHTS = {
    OperationStatus.SETTLED: 55,
    OperationStatus.PENDING: 12,
    OperationStatus.UNDER_REVIEW: 8,
    OperationStatus.REJECTED: 10,
    OperationStatus.RETURNED: 7,
    OperationStatus.CANCELLED: 8,
}


def _random_operation(rng: random.Random, op_id: str, office_id: str) -> Operation:
    op_type = rng.choice(list(TYPE_PROFILE))
    (low, high), concepts = TYPE_PROFILE[op_type]
    status = rng.choices(list(STATUS_WEIGHTS), weights=list(STATUS_WEIGHTS.values()))[0]
    created = datetime(2025, 8, 1, tzinfo=TZ) + timedelta(
        days=rng.randint(0, 58), hours=rng.randint(8, 19), minutes=rng.randint(0, 59)
    )
    updated = created + timedelta(minutes=rng.randint(0, 3 * 24 * 60))
    currency = (
        rng.choice(["USD", "GBP"]) if op_type is OperationType.INTERNATIONAL_TRANSFER else "EUR"
    )
    return Operation(
        id=op_id,
        type=op_type,
        status=status,
        amount=(Decimal(rng.randint(low * 100, high * 100)) / 100).quantize(Decimal("0.01")),
        currency=currency,
        office_id=office_id,
        concept=rng.choice(concepts),
        created_at=created,
        updated_at=updated,
    )


def generate() -> list[Operation]:
    rng = random.Random(SEED)
    operations = list(CURATED)
    used_ids = {op.id for op in operations} | RESERVED_IDS
    offices = list(OFFICE_WEIGHTS)
    while len(operations) < TOTAL:
        op_id = f"OP-{rng.randint(100000, 998999)}"
        if op_id in used_ids:
            continue
        used_ids.add(op_id)
        office_id = rng.choices(offices, weights=list(OFFICE_WEIGHTS.values()))[0]
        operations.append(_random_operation(rng, op_id, office_id))
    return sorted(operations, key=lambda op: op.id)


def main() -> None:
    payload = {
        "notice": NOTICE,
        "operations": [op.model_dump(mode="json") for op in generate()],
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {TOTAL} operations to {OUTPUT}")


if __name__ == "__main__":
    main()
