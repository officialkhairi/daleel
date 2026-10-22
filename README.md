# Daleel · دليل

A bilingual (Arabic + English) copilot for enterprise documents. Upload policies and contracts, ask questions,
get streamed answers that cite the exact passage, and let an agent propose actions that a human approves.

The full spec is in [docs/PLAN.md](docs/PLAN.md). The project is built in six gated phases.

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Foundations: monorepo, compose stack, Keycloak SSO, `/api/me`, CI | Done |
| 2 | Streaming chat over SSE through a provider-agnostic `LLMProvider` | Done |
| 3 | RAG ingestion, hybrid retrieval, citations, PDF highlight | Done |
| 4 | Agent loop with human approvals, audit log | Next |
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

## Documents and citations

Editors and admins upload PDF or Word files on the **Documents** page and choose which roles may see each one.
The worker parses the file (keeping each passage's page and position), splits it into ~500-token chunks under
their headings, embeds them, and indexes them for vector and keyword search; progress streams to the page.

Every answer is grounded in the six best passages the asker is allowed to read. Sources appear as numbered
chips: hover for the excerpt, click to open the PDF at that page with the passage highlighted. Citations to
anything that wasn't retrieved are removed before they reach you.

Demo documents (fictional company) are in [docs/demo](docs/demo): an Arabic procurement policy and an English
security policy.

### Choosing an embedding model

| `EMBEDDINGS_PROVIDER` | What it does |
| --- | --- |
| `fake` (default) | Hashes words into vectors: works offline, behaves like keyword search |
| `sentence_transformers` | Runs `BAAI/bge-m3` in the worker (downloads ~2.3 GB on first start). Multilingual: an English question finds Arabic passages |
| `openai_compat` | Any `/v1/embeddings` server, e.g. Ollama with `bge-m3` (`EMBEDDINGS_BASE_URL=http://ollama:11434/v1`, `EMBEDDINGS_MODEL=bge-m3`) |

Switching provider or model requires re-uploading documents, because vectors from different models can't be
compared.

## Choosing a model

`make up` starts with `LLM_PROVIDER=fake`, which streams "You said: …" so everything works without a model.
To use a real one, set these in `.env` and run `make up` again. Any OpenAI-compatible `/chat/completions` server
works.

| Server | `LLM_BASE_URL` | `LLM_MODEL` | `LLM_API_KEY` |
| --- | --- | --- | --- |
| Ollama on your machine | `http://host.docker.internal:11434/v1` | `falcon3:3b` | empty |
| Ollama in compose (`--profile local-llm`) | `http://ollama:11434/v1` | `falcon3:3b` | empty |
| vLLM | `http://<host>:8000/v1` | the served model name | optional |
| AI71 (hosted Falcon) | the base URL from your AI71 account | e.g. a Falcon model id | your key |
| OpenAI | `https://api.openai.com/v1` | e.g. `gpt-4o-mini` | your key |

Always also set `LLM_PROVIDER=openai_compat`. If the server rejects `stream_options`, set `LLM_STREAM_USAGE=false`.
`LLM_PRICE_IN_PER_MTOK` / `LLM_PRICE_OUT_PER_MTOK` turn token counts into the cost shown in `usage` events.

## Development

```bash
make install   # uv sync + pnpm install
make infra     # backing services only
make dev-api   # API on :8000 with reload (runs migrations first)
make dev-web   # Vite on :5173, proxies /api to :8000
make lint      # ruff, mypy, eslint, tsc
make test      # pytest (Testcontainers Postgres, Redis, MinIO) + vitest
make e2e       # Playwright against the stack, with the fake LLM (then `make up` to restore .env)
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

## How streaming works

`POST /api/chats/{id}/messages` stores the question, starts a run in the background and returns
`text/event-stream`: `run.started`, `token`…, `usage`, optionally `error`, and always a final `run.completed`.
The run writes every event to a Redis Stream, and the HTTP response just reads that stream. So:

- **A dropped connection loses nothing.** The client reconnects to `GET /api/runs/{id}/events` with
  `Last-Event-ID` and continues where it stopped. Reloading the page resumes an answer that is still generating.
- **Stop is a server-side cancel** (`POST /api/runs/{id}/cancel`). The partial answer is saved and marked stopped.
- **Errors are data.** Provider failures arrive as an `error` event with `retryable`; the UI offers Try again,
  which regenerates the last answer (`POST /api/chats/{id}/retry`).

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [ADR 0002](docs/adr/0002-sse-with-redis-streams.md).

## Layout

```
apps/api         FastAPI: auth/, db/ (Alembic), api/, llm/ (provider contract), observability/
apps/worker      Arq jobs: parsing (PyMuPDF, python-docx), chunking, embeddings
apps/web         React 19 + Vite SPA (features/chat, documents, citations, auth, profile)
e2e              Playwright end-to-end tests
packages/ui      Design tokens (Tailwind v4 theme)
deploy/compose   docker-compose.yml, Keycloak realm, Postgres init
docs             PLAN.md, ARCHITECTURE.md, adr/, demo/ (sample policies)
```
