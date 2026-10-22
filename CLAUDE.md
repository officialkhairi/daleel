# Daleel — Bilingual Enterprise Doc Copilot

Portfolio project targeting the TII/AIDRC "Full-stack Engineer, AI Applications" role.
Arabic + English copilot: upload enterprise docs → chat with streamed, cited answers → agent proposes actions that a human approves.
Full spec: `docs/PLAN.md`. Read it before starting any phase.

## Golden rules
- Build ONE phase at a time (see docs/PLAN.md "Phases"). Do not start the next phase until the current gate passes and I confirm.
- Every phase ends with: tests green, `make up` works, README section updated, a git commit + tag `phase-N`.
- Never hard-code secrets. Everything configurable via `.env` (commit `.env.example` only).
- No LangChain/LlamaIndex. The agent loop, SSE protocol, and citation logic are hand-written — that is the point of the project.
- All LLM calls go through `apps/api/app/llm/base.py::LLMProvider`. Tests use `FakeProvider` only — CI never calls a real model.
- RBAC and tenant/ACL filtering are enforced server-side (API + SQL). UI hiding is cosmetic only.
- Side-effect tools (`send_email`, `create_ticket`, `flag_clause`) ALWAYS require human approval, regardless of model output.
- Every UI string goes through i18next with `en` and `ar`; use CSS logical properties so RTL works.

## Stack (do not swap without asking)
- Frontend: React 19, TypeScript (strict), Vite, TanStack Query, Zustand, Tailwind, Radix UI, i18next, react-pdf, oidc-client-ts. pnpm workspaces.
- Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic, Arq, uv for deps.
- Data: Postgres 16 + pgvector, Redis 7, MinIO.
- Auth: Keycloak (realm import in `deploy/compose/keycloak/realm.json`), roles: viewer, editor, approver, admin.
- LLM: OpenAI-compatible client (Falcon via vLLM/Ollama/AI71, OpenAI), plus Anthropic. Env: LLM_PROVIDER, LLM_BASE_URL, LLM_MODEL, LLM_API_KEY.
- Embeddings: BAAI/bge-m3 (1024-dim) via sentence-transformers in the worker; allow an `EMBEDDINGS_PROVIDER=fake` for tests.
- Observability: OpenTelemetry, Prometheus, Grafana, Langfuse (compose profile `obs`).
- Tests: pytest + httpx + Testcontainers, Vitest + Testing Library, Playwright, Storybook.

## Layout
```
apps/web            React SPA
apps/api/app        api/ agent/ llm/ rag/ auth/ db/ streaming/ observability/
apps/worker         Arq jobs
apps/mock-ticketing Fake Jira/ServiceNow
packages/ui         Design tokens + components + Storybook
evals/              golden.jsonl + run_evals.py
deploy/compose      docker-compose.yml, keycloak realm, grafana dashboards
deploy/helm/daleel  Helm chart
docs/               PLAN.md, ARCHITECTURE.md, adr/
```

## Commands (keep these working)
- `make up` / `make down` — full stack via Docker Compose
- `make test` — backend + frontend unit/integration tests
- `make e2e` — Playwright against compose with FakeProvider
- `make lint` — ruff, mypy, eslint, tsc
- `make evals` — run golden-set evals

## Code style
- Python: ruff + mypy strict, async everywhere, Pydantic models for every request/response and tool arg schema.
- TS: no `any`, feature folders (`features/chat`, `features/documents`, ...), components accessible (keyboard + aria).
- Errors: API returns `ErrorEnvelope {code, message, retryable}`; never leak stack traces.
- Small, reviewable commits with conventional-commit messages.
