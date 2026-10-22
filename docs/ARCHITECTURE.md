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

## Known simplifications (Phase 1)

- One tenant per realm: `tenant` is a hard-coded claim (`acme`) on each client. Multi-tenant realms
  (Keycloak Organizations or a declared user-profile attribute) come with the admin console in Phase 5.
- `/api/me` writes on every call to keep the profile fresh. Fine at this scale; revisit if it shows up in traces.
- The SPA's OIDC settings are baked in at build time (`VITE_*`).
