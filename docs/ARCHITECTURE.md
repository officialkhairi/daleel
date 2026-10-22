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

## Phase 3: documents, retrieval, citations

```
upload ─▶ API ─▶ MinIO + documents row ─▶ Arq job ─▶ worker: parse → chunk → embed → chunks (pgvector, tsvector)
                                                        └─ progress ─▶ Redis pub/sub ─▶ API WebSocket ─▶ browser
question ─▶ run ─▶ retrieve (vector ∥ keyword → RRF, role filter in SQL) ─▶ sources in prompt ─▶ model
                    model tokens ─▶ citation filter ─▶ token + citation events ─▶ chips ─▶ PDF + highlight
```

- **Parsing keeps positions.** Every PDF block keeps its page and box (points, top-left origin), which become the
  chunk's `bboxes` and later the highlight. Many PDFs store Arabic in visual order and map ligatures back to
  their letters reversed, so mostly-Arabic lines are rebuilt from character positions (right to left, Latin and
  numbers restored to their own order, ligature pairs kept together, diacritics dropped). Generators that lose
  letters entirely (e.g. some lam-alef ligatures) still lose them; OCR would be the fix.
- **Chunks** follow headings (never span two sections), aim for ~500 tokens, and repeat ~15% of the previous
  chunk. The heading is embedded with the text and counted in keyword search.
- **Retrieval** runs vector search (HNSW, cosine, iterative scans so filters don't starve results) and keyword
  search (`tsvector` per chunk language; the query is stemmed as both English and Arabic, words OR'ed) in
  parallel, then fuses them with reciprocal rank fusion (k = 60) and keeps 6. Both queries filter
  `documents.acl_roles && user roles` and `status = 'ready'`; RLS adds the tenant. If the embedding model is
  unavailable, keyword search still answers.
- **Embeddings for queries** come from the same model as documents. With `sentence_transformers` the model lives
  only in the worker; the API enqueues an `embed_texts` job and waits for its result (polled every 20 ms), so the
  API image has no PyTorch.
- **Prompt.** Sources are numbered `<source n="…" title="…" page="…">` blocks appended to the system prompt; their
  text is HTML-escaped so a document can't close the tag and pose as instructions.
- **Citations.** A streaming filter holds back a possible `[n]` until it is complete, drops numbers that weren't
  retrieved (counted in `runs.state.dropped_citations`), and emits a `citation` event the first time each source
  is cited. The answer is saved with its citations, so they survive reloads.
- **Viewer.** The SPA fetches the original file with the user's token (same role check), renders the cited page
  with pdf.js, and draws the boxes over it. PDF coordinates are physical, so the viewer stays LTR inside an
  Arabic layout.
- **Progress.** The worker publishes to `tenant:{id}:documents`; the WebSocket (authenticated by its first
  message, never the URL) forwards only events for documents the viewer's roles may see, and closes when the
  token expires.

## Known simplifications

- One tenant per realm: `tenant` is a hard-coded claim (`acme`) on each client. Multi-tenant realms
  (Keycloak Organizations or a declared user-profile attribute) come with the admin console in Phase 5.
- `/api/me` writes on every call to keep the profile fresh. Fine at this scale; revisit if it shows up in traces.
- The SPA's OIDC settings are baked in at build time (`VITE_*`).
- Runs execute inside the API process. An API restart ends in-flight runs with a retryable `server_shutdown`
  error. Moving runs to the Arq worker is possible without changing the protocol, since clients only ever
  read the Redis Stream.
- Token usage comes from the provider; servers that don't report it produce no `usage` event.
- Object storage uses the MinIO root credentials locally; production would use a scoped access key.
- Scanned PDFs (no text layer) fail with a clear message; there is no OCR.
- No reranker yet: fusion output goes straight to the prompt.
