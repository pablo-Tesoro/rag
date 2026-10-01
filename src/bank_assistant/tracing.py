"""Traces in LangSmith: opt-in, with identifiers masked before they leave the process.

Logs carry no content (D-10). Traces do, because debugging an agent needs the question, the
retrieved documents and every model step. Two safeguards keep that acceptable:

- Opt-in through our own switch, `TRACE_TO_LANGSMITH`. LangChain's `LANGSMITH_TRACING`
  turns on a global tracer that would upload every run without the anonymizer below, so it
  stays off and the tracer is passed explicitly in each run's config.
- An anonymizer runs on every input, output, error and metadata before upload. Employee ids
  become the same HMAC pseudonym the logs use, so a log line and its trace can be matched.
  Customer identifiers an employee might type (DNI, NIE, IBAN, email, phone) become
  placeholders. The corpus is fictitious and has none; this is defence in depth.
"""

import logging
import re

from langchain_core.tracers import LangChainTracer
from langsmith import Client
from langsmith.anonymizer import create_anonymizer
from langsmith.utils import tracing_is_enabled

from bank_assistant.config import Settings
from bank_assistant.logs import pseudonymize

log = logging.getLogger(__name__)

EMPLOYEE_ID = re.compile(r"\bEMP-\d{3}\b")
# Order matters: NIE before DNI, so "X1234567L" is not half-matched as a DNI.
CUSTOMER_IDENTIFIERS = (
    (re.compile(r"\b[XYZ]\d{7}[A-Z]\b"), "[NIE]"),
    (re.compile(r"\b\d{8}[A-Z]\b"), "[DNI]"),
    (re.compile(r"\bES\d{2}(?:[ -]?\d{4}){5}\b"), "[IBAN]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"), "[EMAIL]"),
    # Spanish phone numbers: 9 digits starting with 6-9, optionally +34 and grouped.
    (re.compile(r"(?<![\w-])(?:\+34[ -]?)?[6-9]\d{2}(?:[ -]?\d{3}){2}(?![\w-])"), "[TELEFONO]"),
)


def mask_text(text: str, pseudonym_key: str) -> str:
    text = EMPLOYEE_ID.sub(lambda m: f"emp_{pseudonymize(m.group(), pseudonym_key)}", text)
    for pattern, placeholder in CUSTOMER_IDENTIFIERS:
        text = pattern.sub(placeholder, text)
    return text


def build_tracer(settings: Settings, *, project: str | None = None) -> LangChainTracer | None:
    """The LangSmith tracer to pass in each run's callbacks, or None when tracing is off."""
    if tracing_is_enabled():
        # Runs invoked without our tracer would be uploaded unmasked by LangChain's own.
        log.warning("tracing.global_tracer_enabled", extra={"fields": {"env": "LANGSMITH_TRACING"}})
    if not settings.trace_to_langsmith:
        return None
    api_key = settings.langsmith_api_key.get_secret_value() if settings.langsmith_api_key else ""
    if not api_key:
        # Tracing is optional: missing configuration must not stop the service.
        log.error("tracing.disabled", extra={"fields": {"reason": "LANGSMITH_API_KEY is empty"}})
        return None
    pseudonym_key = settings.log_pseudonym_key.get_secret_value()

    def mask(text: str, _path: list[str | int]) -> str:
        return mask_text(text, pseudonym_key)

    client = Client(
        api_url=settings.langsmith_endpoint,
        api_key=api_key,
        anonymizer=create_anonymizer(mask),
    )
    return LangChainTracer(project_name=project or settings.langsmith_project, client=client)
