.DEFAULT_GOAL := help
.PHONY: help setup up down data lint format typecheck test check ingest eval-retrieval eval eval-ablation

UV ?= uv

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

setup: ## Install Python deps with uv and create .env from .env.example if missing
	$(UV) sync --all-groups
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")

up: ## Start the stack with docker compose and wait until it is healthy
	docker compose up -d --wait

down: ## Stop the stack (data volume is kept)
	docker compose down

data: ## Regenerate the fictitious PDFs and core-banking operations (deterministic)
	$(UV) run --group data python scripts/build_pdfs.py
	$(UV) run python scripts/generate_operations.py

lint: ## Ruff lint + format check
	$(UV) run ruff check .
	$(UV) run ruff format --check .

format: ## Apply ruff fixes and formatting
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

typecheck: ## mypy (strict)
	$(UV) run mypy

test: ## Run the test suite
	$(UV) run pytest

check: lint typecheck test ## Everything CI runs

ingest: ## Incrementally ingest data/corpus into Postgres (only changed documents)
	$(UV) run python -m bank_assistant.cli ingest

eval-retrieval: ## Retrieval-only eval (recall@5, MRR) for dense, bm25 and hybrid; no LLM calls
	$(UV) run python -m evals.retrieval_eval --split dev

eval: ## Run the evaluation harness (phase 4)
	@echo "Not implemented yet: arrives in phase 4." && exit 1

eval-ablation: ## Run the retrieval-mode ablation (phase 6)
	@echo "Not implemented yet: arrives in phase 6." && exit 1
