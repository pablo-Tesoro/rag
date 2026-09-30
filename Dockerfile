# syntax=docker/dockerfile:1

# ---- builder: resolve and install dependencies with uv (never shipped) ----------------------
FROM ghcr.io/astral-sh/uv:0.12.21 AS uv

FROM python:3.12-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first, in their own layer: rebuilt only when the lockfile changes.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Then the project itself, installed as a regular (non-editable) package.
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---- runtime: only the virtualenv, the data and the prompts ---------------------------------
FROM python:3.12-slim AS runtime
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /models \
    && chown app:app /models
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --chown=app:app data ./data
COPY --chown=app:app prompts ./prompts
COPY --chown=app:app evals ./evals

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models

USER app
EXPOSE 8000

# Liveness only: /readyz is for orchestrators that route traffic.
HEALTHCHECK --interval=10s --timeout=3s --start-period=120s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]

# No access log: it would put client IPs in the logs; the app logs one event per chat turn.
CMD ["uvicorn", "bank_assistant.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
