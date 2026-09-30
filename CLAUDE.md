# CLAUDE.md

Portfolio project: an agentic assistant for employees of **Banco Olvessa, a fictitious
bank**. RAG over internal policies (with citations and abstention), permission-aware
core-banking lookups, and incident creation behind a human-approval interrupt (LangGraph).
The owner will defend every decision in an AI Software Engineer interview: favour clarity,
good practice and end-to-end correctness over features.

State of the work: `docs/progreso.md`. Design decisions: `docs/decisiones.md`.

## Languages

- Code, comments, commit messages, README, this file: **English**.
- Corpus (`data/corpus`), eval dataset, `docs/progreso.md`, `docs/decisiones.md`: **Spanish**.
- LLM-facing surface (tool names, tool arguments, prompts): **Spanish**, because users and
  documents are Spanish. Internal identifiers stay English.
- Conversation with the owner: Spanish.

## Commands

```bash
make setup      # uv sync --all-groups + .env from .env.example
make up         # build and start db + app (docker compose), wait until healthy
make check      # ruff + mypy (strict) + pytest — must be green before any commit
make data       # regenerate PDFs and operations (deterministic)
make ingest     # load corpus (incremental) + core banking, inside the stack
make ingest-local  # same, with the local uv environment
make eval-retrieval  # recall@5 / MRR per retrieval mode, no LLM calls
uv run python -m bank_assistant.cli search "pregunta" --employee EMP-001 --mode hybrid
```

Integration tests (`tests/integration`) run against the compose Postgres in an isolated
schema per module and are skipped if it is not reachable; `uv run pytest -m "not
integration"` runs only unit tests.

## Layout

- `src/bank_assistant/` — application package (src layout): `ingestion/`, `retrieval/`,
  `agent/` (graph, tools, schemas, guards), `api/`, `core_banking/`, `incidents/`,
  `services.py` (wiring of real dependencies).
- `prompts/` — versioned prompts (`<name>/<version>.md`).
- `data/` — fictitious corpus, employees, core-banking data. See `data/README.md` for the
  deliberate hard cases and which eval category each one serves.
- `evals/` — dataset, schema and (from phase 4) the harness. See `evals/README.md`.
- `scripts/` — deterministic data generators.
- `tests/unit`, `tests/integration` — integration tests need Postgres and are marked.

## Conventions

- Python 3.12, uv, ruff (lint + format), mypy strict, pytest.
- Pydantic models at every boundary (data files, tool arguments, API, eval cases).
- Settings only through `bank_assistant.config.Settings` (env vars / `.env`).
- Tests are deterministic: fake LLM and fake embeddings; no network in unit tests.
- Keep modules small and explicit; no framework magic that cannot be explained.

## Security invariants (do not break)

- Permission and validity filters are applied in the database query, never in the prompt.
- The employee identity comes from the request context, never from LLM tool arguments.
- "Not found" and "not allowed" return the same answer (no existence oracle).
- Retrieved content is delimited and treated as data, not instructions.
- Writes (`abrir_incidencia`) require human approval and are idempotent.
- Logs are JSON without personal data or free text; employee ids are HMAC-pseudonymised.
- Never commit secrets: only `.env.example` is versioned, with every credential left empty
  (`tests/unit/test_env_example.py` enforces it). Real keys live in the local `.env` or in
  the cloud environment settings.

## Data rules

- Everything is fictitious and must say so. No personal data (employees have no names).
- Eval labels point to `(doc_id, section)`, never chunk ids.
- Generated files (`*.pdf`, `*.meta.yaml`, `operations.json`) are only changed through
  `make data`; a test fails if `operations.json` drifts from its generator.

## Workflow

- Work in phases (see `docs/progreso.md`). At the end of each phase: `make check` green,
  one clear commit, a Spanish summary to the owner, update `docs/progreso.md` and
  `docs/decisiones.md`, then **stop and wait for the owner's OK**.
- Cost: the LLM must be free (Gemini API free tier). Use `--limit` for quick runs and ask
  before a full eval run (free-tier rate limits).
- Never invent results: every number in the README comes from a run saved in `evals/results/`.
- If something does not work as expected, say so and propose an alternative.
