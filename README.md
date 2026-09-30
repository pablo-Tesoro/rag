# Banco Olvessa — employee assistant (portfolio project)

> **Everything in this repository is fictitious.** Banco Olvessa does not exist; its
> policies, employees and operations are invented for demonstration purposes.

An agentic assistant for the employees of a fictitious bank, built with LangGraph:

1. Answers questions about internal policies with RAG, citing sources and abstaining when
   there is no evidence.
2. Looks up operations in a simulated core-banking system, respecting the employee's
   permissions.
3. Opens incidents only after human approval (LangGraph interrupt).

Status: work in progress, built in phases. See [docs/progreso.md](docs/progreso.md).
