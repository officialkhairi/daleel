# ADR 0001: Monorepo layout and core stack

- Status: accepted
- Date: 2026-10-22

## Context

Daleel has a Python API, a TypeScript SPA, a worker, and shared UI tokens. One person builds it in gated phases,
and reviewers need to run the whole system with one command.

## Decision

- **One repository.** `apps/*` for deployables, `packages/*` for shared TypeScript, `deploy/` for infrastructure.
- **Two toolchains, no meta build tool.** uv owns `apps/api` (and later `apps/worker`). A pnpm workspace owns
  `apps/web` and `packages/*`. The Makefile is the only entry point that spans both.
- **Keycloak for identity** instead of hand-rolled auth: realistic enterprise SSO (PKCE, JWKS rotation, roles)
  that the API validates exactly as it would against any OIDC provider.
- **Postgres row-level security for tenancy**, with the API connecting as a role that cannot bypass it, so a
  missing `WHERE tenant_id = …` cannot leak data.
- **No LLM framework.** The provider contract (`app/llm/base.py`), agent loop, SSE protocol and citations are
  hand-written (see CLAUDE.md).

## Consequences

- Contributors need Docker, uv and Node; `make up` needs only Docker.
- Every new table needs its RLS policy in the same migration. Phase 5 adds a test that fails when a table has
  `tenant_id` but no policy.
- The official MinIO images stopped being published in 2025; compose uses Chainguard's MinIO build pinned by
  digest. Swapping to another S3-compatible store later only touches compose and the storage client.
