SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE := docker compose -p daleel -f deploy/compose/docker-compose.yml --env-file .env
API := cd apps/api &&
PNPM := corepack pnpm

.PHONY: help
help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

.env:
	cp .env.example .env

# --- stack ---------------------------------------------------------------

.PHONY: up
up: .env ## Build and start the full stack, wait until healthy
	$(COMPOSE) up -d --build --wait

.PHONY: down
down: ## Stop the stack (keeps volumes)
	$(COMPOSE) down

.PHONY: nuke
nuke: ## Stop the stack and delete volumes
	$(COMPOSE) down -v

.PHONY: infra
infra: .env ## Start only backing services (for make dev-api / dev-web)
	$(COMPOSE) up -d --wait postgres redis minio minio-init keycloak mailpit

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
	$(PNPM) install

.PHONY: migrate
migrate: .env ## Apply database migrations (host)
	$(API) uv run alembic upgrade head

.PHONY: dev-api
dev-api: .env migrate ## Run the API on the host with reload
	$(API) uv run uvicorn app.main:app --reload --port 8000

.PHONY: dev-web
dev-web: ## Run the SPA on the host with Vite
	$(PNPM) --filter @daleel/web dev

# --- quality -------------------------------------------------------------

.PHONY: lint
lint: ## ruff, mypy, eslint, tsc
	$(API) uv run ruff check . && uv run ruff format --check . && uv run mypy
	$(PNPM) -r run lint
	$(PNPM) -r run typecheck

.PHONY: fmt
fmt: ## Auto-format
	$(API) uv run ruff check --fix . && uv run ruff format .

.PHONY: test
test: test-api test-web ## Backend + frontend tests

.PHONY: test-api
test-api:
	$(API) uv run pytest

.PHONY: test-web
test-web:
	$(PNPM) -r run test

.PHONY: smoke
smoke: .env ## Log in as each seeded user against the running stack and call /api/me
	./scripts/smoke.sh

.PHONY: e2e
e2e: ## Playwright end-to-end tests
	@echo "e2e: not yet (Playwright arrives in Phase 3)"

.PHONY: evals
evals: ## Golden-set evals
	@echo "evals: not yet (arrives in Phase 6)"
