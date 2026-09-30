"""Structured JSON logging without personal data.

Policy:
- Log events, ids and measurements, never free text written by employees or customers
  (questions, answers, document content). That content belongs in traces, which have
  their own access control and retention.
- Employee ids are pseudonymised with `pseudonymize` before they reach a log line.
- Structured fields are passed explicitly: `log.info("event", extra={"fields": {...}})`.
"""

import hashlib
import hmac
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


# Third-party loggers that are chatty at INFO (one line per HTTP request, model loading).
NOISY_LOGGERS = ("httpx", "httpcore", "huggingface_hub", "sentence_transformers", "transformers")


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    # uvicorn installs its own plain-text handlers: route its logs through the JSON one.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    # The access log records client IPs (personal data): off, whatever the CLI flags say.
    # The app logs its own pseudonymised event per chat turn instead.
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    access.disabled = True


def pseudonymize(value: str, key: str) -> str:
    """Stable reference for an identifier (e.g. an employee id) that cannot be reversed
    without the key.

    A plain hash would not be enough: employee ids come from a small space and could be
    brute-forced. HMAC with a secret key keeps log lines correlatable but not reversible.
    """
    return hmac.new(key.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()[:12]
