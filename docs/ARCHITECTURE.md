# Architecture

This page grows phase by phase. It covers what exists today.

## Phase 1: identity and tenancy

```
Browser (SPA) ──PKCE──▶ Keycloak (realm "daleel")
     │                       │ JWKS
     │ Bearer token          ▼
     └──────/api────▶ nginx ─▶ FastAPI ──▶ Postgres (RLS, app role)
```

- **Tokens.** Access tokens carry `aud=daleel-api`, `realm_access.roles` and `tenant`. The API accepts RS256 only
  and checks `iss`, `aud`, `exp`. Keys are cached for `JWKS_CACHE_TTL_SECONDS`; an unknown `kid` triggers at most
  one refetch per `jwks_min_refresh_seconds`.
- **Issuer vs. backchannel.** Keycloak always issues tokens for `http://localhost:8180` (what the browser sees,
  `KC_HOSTNAME`). The API container fetches JWKS from `http://keycloak:8080` (`KC_HOSTNAME_BACKCHANNEL_DYNAMIC`).
- **Tenancy.** The tenant id is `uuid5(namespace, tenant_slug)`, so it is known from the token alone. Each request
  that touches the database runs in one transaction with `set_config('app.tenant_id', …, true)`. Every table has
  `ENABLE` + `FORCE ROW LEVEL SECURITY` and a `tenant_isolation` policy. An unset tenant sees no rows.
- **Database roles.** `POSTGRES_USER` owns the schema and runs migrations (one-shot `migrate` service). The API
  connects as `APP_DB_USER` (`NOSUPERUSER NOBYPASSRLS`). Default privileges grant it DML on future tables.
- **Errors.** Every non-2xx response body is `ErrorEnvelope {code, message, retryable}`; unhandled exceptions
  are logged with the request id and returned as `internal_error`.

## Phase 2: streaming chat

```
SPA ──POST /messages──▶ API ──start run (task)──▶ LLMProvider ──▶ model server
 ▲                       │                            │
 │   text/event-stream   │ XREAD                      │ XADD token…
 └───────────────────────┴──────── Redis Stream run:{id}:events ◀┘
```

- **Run lifecycle.** `start_run` locks the chat row (one run per chat), stores the user message and a `runs`
  row, and commits. The API publishes `run.started`, spawns `execute_run` as an asyncio task (held by
  `TaskRegistry`), and returns an SSE response that reads the run's stream. The task streams the provider into
  the stream, then saves the assistant message and the run's final status in one transaction, and publishes
  `run.completed` last, so a client that sees it can refetch and find the saved message.
- **Resume.** Redis Stream entry ids are the SSE `id`s. `GET /api/runs/{id}/events` replays after
  `Last-Event-ID` (or from the start) and then blocks for new entries, sending a `: ping` comment every 15 s.
  Streams expire `RUN_EVENTS_TTL_SECONDS` after their last write; after that the endpoint returns 410 and the
  client reloads the chat from Postgres.
- **Cancel.** `POST /api/runs/{id}/cancel` sets a Redis flag that the run checks every 200 ms. Any replica can
  take the cancel; only the replica running the task needs to see the flag.
- **Failure modes.** Provider errors (`LLMError`, classified as retryable or not), unexpected exceptions and
  shutdown (`server_shutdown`) all end with `error` + `run.completed(finish_reason="error")`; text produced so far
  is saved with `status="error"`. A run still marked `running` after 15 minutes is treated as abandoned.
- **Providers.** `OpenAICompatProvider` parses the OpenAI SSE format by hand (text, usage, and tool-call fragments
  re-assembled by index for Phase 4). `FakeProvider` replays scripted turns (JSON) or echoes; tests, CI and the
  default stack use it, so no test calls a real model.

## Known simplifications

- One tenant per realm: `tenant` is a hard-coded claim (`acme`) on each client. Multi-tenant realms
  (Keycloak Organizations or a declared user-profile attribute) come with the admin console in Phase 5.
- `/api/me` writes on every call to keep the profile fresh. Fine at this scale; revisit if it shows up in traces.
- The SPA's OIDC settings are baked in at build time (`VITE_*`).
- Runs execute inside the API process. An API restart ends in-flight runs with a retryable `server_shutdown`
  error. Moving runs to the Arq worker is possible without changing the protocol, since clients only ever
  read the Redis Stream.
- Token usage comes from the provider; servers that don't report it produce no `usage` event.
