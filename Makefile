SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE := docker compose -p daleel -f deploy/compose/docker-compose.yml --env-file .env
API := cd apps/api &&
WORKER := cd apps/worker &&
PNPM := corepack pnpm

.PHONY: help
help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

.env:
	cp .env.example .env

# --- stack ---------------------------------------------------------------

.PHONY: up
# --wait treats exited one-shot jobs (migrate, minio-init) as failures, so wait on the
# long-running services only; the jobs still run as their dependencies.
up: .env ## Build and start the full stack, wait until healthy
	$(COMPOSE) up -d --build --wait api web worker mailpit redis

.PHONY: obs
obs: .env ## Stack plus tracing/metrics: Grafana :3001, Prometheus :9091, Langfuse :3000
	OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318 VITE_OTEL=true \
		$(COMPOSE) --profile obs up -d --build --wait api web worker mailpit redis grafana langfuse-web langfuse-worker otel-collector prometheus

.PHONY: down
down: ## Stop the stack (keeps volumes)
	$(COMPOSE) down

.PHONY: nuke
nuke: ## Stop the stack and delete volumes
	$(COMPOSE) down -v

.PHONY: infra
infra: .env ## Start only backing services (for make dev-api / dev-web)
	$(COMPOSE) up -d --wait postgres redis minio keycloak mailpit
	$(COMPOSE) up minio-init

.PHONY: logs
logs: ## Tail logs
	$(COMPOSE) logs -f --tail=100

.PHONY: ps
ps: ## Show service status
	$(COMPOSE) ps

# --- local dev -----------------------------------------------------------

.PHONY: install
install: ## Install backend and frontend dependencies
	$(API) uv sync
	$(WORKER) uv sync
	$(PNPM) install

.PHONY: migrate
migrate: .env ## Apply database migrations (host)
	$(API) uv run alembic upgrade head

.PHONY: dev-api
dev-api: .env migrate ## Run the API on the host with reload
	$(API) uv run uvicorn app.main:create_app --factory --reload --port 8000

.PHONY: dev-web
dev-web: ## Run the SPA on the host with Vite
	$(PNPM) --filter @daleel/web dev

# --- quality -------------------------------------------------------------

.PHONY: lint
lint: ## ruff, mypy, eslint, tsc
	$(API) uv run ruff check . && uv run ruff format --check . && uv run mypy
	$(WORKER) uv run ruff check . && uv run ruff format --check . && uv run mypy
	$(WORKER) uv run ruff check --config pyproject.toml ../../evals \
		&& uv run ruff format --config pyproject.toml --check ../../evals && uv run mypy ../../evals
	$(PNPM) -r run lint
	$(PNPM) -r run typecheck

.PHONY: fmt
fmt: ## Auto-format
	$(API) uv run ruff check --fix . && uv run ruff format .
	$(WORKER) uv run ruff check --fix . && uv run ruff format .
	$(WORKER) uv run ruff check --config pyproject.toml --fix ../../evals && uv run ruff format --config pyproject.toml ../../evals

.PHONY: test
test: test-api test-worker test-web ## Backend + frontend tests

.PHONY: test-api
test-api:
	$(API) uv run pytest

.PHONY: test-worker
test-worker:
	$(WORKER) uv run pytest

.PHONY: test-web
test-web:
	$(PNPM) -r run test

.PHONY: smoke
smoke: .env ## Log in as each seeded user against the running stack and call /api/me
	./scripts/smoke.sh

# The e2e run switches the stack to the fake LLM and embeddings (deterministic, no model).
# Run `make up` afterwards to go back to the settings in .env.
E2E_ENV := LLM_PROVIDER=fake LLM_MODEL=fake-echo LLM_FAKE_DELAY_MS=150 EMBEDDINGS_PROVIDER=fake

.PHONY: e2e
e2e: .env ## Playwright end-to-end tests against the compose stack (fake LLM)
	$(E2E_ENV) $(COMPOSE) up -d --build --wait api web worker mailpit redis
	$(PNPM) --filter @daleel/e2e exec playwright install chromium
	$(PNPM) --filter @daleel/e2e run test:e2e
	@echo "Stack is in e2e mode (fake LLM). Run 'make up' to restore your .env settings."

# Deterministic by default (as in CI). To evaluate a real model, override, e.g.
#   make evals EVALS_ENV="LLM_PROVIDER=openai_compat LLM_BASE_URL=http://localhost:11434/v1 LLM_MODEL=qwen2.5:3b"
EVALS_ENV ?= LLM_PROVIDER=fake LLM_MODEL=fake-echo EMBEDDINGS_PROVIDER=fake

.PHONY: evals
evals: ## Golden-set evals: recall@6, citation precision, faithfulness (evals/golden.jsonl)
	$(WORKER) env $(EVALS_ENV) uv run python ../../evals/run_evals.py
