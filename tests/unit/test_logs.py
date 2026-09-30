import json
import logging

from bank_assistant.logs import JsonFormatter, configure_logging, pseudonymize


def _record(message: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, message, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formatter_emits_one_json_object_with_structured_fields() -> None:
    line = JsonFormatter().format(_record("chat.completed", fields={"latency_ms": 812}))

    payload = json.loads(line)
    assert payload["event"] == "chat.completed"
    assert payload["level"] == "INFO"
    assert payload["latency_ms"] == 812


def test_formatter_keeps_non_ascii_readable() -> None:
    line = JsonFormatter().format(_record("operación"))

    assert "operación" in line


def test_pseudonymize_is_stable_keyed_and_not_the_raw_id() -> None:
    ref = pseudonymize("EMP-001", key="k1")

    assert ref == pseudonymize("EMP-001", key="k1")
    assert ref != pseudonymize("EMP-001", key="k2")
    assert "EMP-001" not in ref


def test_access_log_with_client_ips_is_disabled() -> None:
    configure_logging("INFO")

    assert logging.getLogger("uvicorn.access").disabled is True
