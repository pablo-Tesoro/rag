# Banco Olvessa — employee assistant (portfolio project)

> **Everything in this repository is fictitious.** Banco Olvessa does not exist; its
> policies, employees and operations are invented for demonstration purposes.

An agentic assistant for the employees of a fictitious bank, built with LangGraph:

1. Answers questions about internal policies with RAG, citing sources and abstaining when
   there is no evidence.
2. Looks up operations in a simulated core-banking system, respecting the employee's
   permissions.
3. Opens incidents only after human approval (LangGraph interrupt).

Status: work in progress, built in phases. See [docs/progreso.md](docs/progreso.md) and the
design decisions in [docs/decisiones.md](docs/decisiones.md) (Spanish).

## Quickstart (preview; the full README comes in phase 6)

Requirements: Docker and make. A free Gemini API key from Google AI Studio.

```bash
cp .env.example .env          # then set GOOGLE_API_KEY in .env (never commit it)
make up                       # builds the image, starts Postgres + API, waits until healthy
make ingest                   # loads the fictitious corpus and core-banking data
curl -s localhost:8000/readyz
curl -s -X POST localhost:8000/chat -H 'Content-Type: application/json' \
     -H 'X-Employee-Id: EMP-001' \
     -d '{"message": "¿Cuál es el límite diario de una transferencia inmediata en oficina?"}'
```
