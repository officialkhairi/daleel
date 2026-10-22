# Daleel · دليل

A bilingual (Arabic + English) copilot for enterprise documents. Upload policies and contracts, ask questions,
get streamed answers that cite the exact passage, and let an agent propose actions that a human approves.

The full spec is in [docs/PLAN.md](docs/PLAN.md). The project is built in six gated phases.

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Foundations: monorepo, compose stack, Keycloak SSO, `/api/me`, CI | Done |
| 2 | Streaming chat over SSE through a provider-agnostic `LLMProvider` | Next |
| 3 | RAG ingestion, hybrid retrieval, citations, PDF highlight | |
| 4 | Agent loop with human approvals, audit log | |
| 5 | RBAC/ACL everywhere, admin console, observability, Storybook | |
| 6 | Evals in CI, Helm, release, live demo | |

## Quick start

Requirements: Docker with Compose v2, GNU Make. For running tests on the host: [uv](https://docs.astral.sh/uv/)
and Node 24 (pnpm comes from Corepack).

```bash
make up        # builds and starts everything; first run copies .env.example to .env
make smoke     # logs in as each demo user and checks roles + RBAC against the running stack
```

Open <http://localhost:5173> and sign in. Demo users (local only, password `demo`):

| User | Roles | `/api/admin/ping` |
| --- | --- | --- |
| `officer` | editor, approver | 403 |
| `viewer` | viewer | 403 |
| `admin` | admin | 200 |

| Service | URL |
| --- | --- |
| Web app | <http://localhost:5173> |
| API (OpenAPI docs) | <http://localhost:8000/docs> |
| Keycloak admin (`admin` / see `.env`) | <http://localhost:8180> |
| Mailpit | <http://localhost:8025> |
| MinIO console | <http://localhost:9001> |

Keycloak runs on 8180, not 8080, because 8080 is often taken. Change `KEYCLOAK_PORT` and the URLs that use it in
`.env` if needed.

## Development

```bash
make install   # uv sync + pnpm install
make infra     # backing services only
make dev-api   # API on :8000 with reload (runs migrations first)
make dev-web   # Vite on :5173, proxies /api to :8000
make lint      # ruff, mypy, eslint, tsc
make test      # pytest (Testcontainers Postgres) + vitest
make down      # stop; `make nuke` also deletes volumes
```

## How login works

1. The SPA redirects to Keycloak (Authorization Code + PKCE, public client `daleel-web`).
2. Keycloak returns an access token with `aud=daleel-api`, realm roles, and a `tenant` claim.
3. The SPA calls `/api/me` with the bearer token.
4. The API verifies the token itself against Keycloak's JWKS (cached, RS256 only, issuer and audience checked).
5. The API upserts the user inside a transaction scoped to the tenant: Postgres row-level security reads
   `app.tenant_id`, and the API connects as a non-superuser role, so the policy always applies.

Roles from the SPA are never trusted. Hiding UI is cosmetic; `require(role)` on the API decides.

## Layout

```
apps/api         FastAPI: auth/, db/ (Alembic), api/, llm/ (provider contract), observability/
apps/web         React 19 + Vite SPA (features/auth, features/profile, i18n/)
packages/ui      Design tokens (Tailwind v4 theme)
deploy/compose   docker-compose.yml, Keycloak realm, Postgres init
docs             PLAN.md, ARCHITECTURE.md, adr/
```
