# Daleel — Build Plan

## Demo story (what must work at the end)
A compliance officer logs in via SSO, uploads an Arabic procurement policy (live ingestion progress), asks in English
"What's the approval threshold for vendor contracts?" → answer streams with [n] citation chips → clicking a chip opens
the PDF at the highlighted passage. She asks "Draft a reminder to procurement" → agent calls `search_documents`, then
proposes `send_email` → approval card (editable args) → she edits + approves → email lands in Mailpit → audit log
records it. A `viewer` user cannot see the approve button or restricted docs. Admin dashboard shows usage, TTFT, cost.

## SSE event protocol — `POST /api/chats/{id}/messages` → text/event-stream
Each event has `id` (for `Last-Event-ID` resume; events buffered in Redis Streams per run).
| event | payload |
|---|---|
| run.started | run_id, model |
| token | text |
| tool.started | call_id, name, args |
| tool.result | call_id, summary, duration_ms |
| citation | n, chunk_id, doc_id, page, bbox, snippet |
| approval.required | approval_id, tool, args, json_schema, risk |
| usage | tokens_in, tokens_out, cost_usd |
| error | code, message, retryable |
| run.completed | message_id, finish_reason |
Client: fetch + ReadableStream parser (POST + auth header), AbortController cancel, reconnect with backoff + Last-Event-ID.

## LLMProvider
```python
class LLMProvider(Protocol):
    async def stream(self, messages, tools, **opts) -> AsyncIterator[LLMEvent]: ...
# LLMEvent = TextDelta | ToolCallDelta | ToolCallDone | Usage | Finish
```
Implementations: OpenAICompatProvider, AnthropicProvider, FakeProvider (replays scripted JSON for tests).
Fallback for models without native tool calling: JSON-schema constrained output (vLLM guided_json), parsed into ToolCallDone.

## Agent loop
Max 6 steps. Stream model → if tool calls: run AUTO tools in parallel (asyncio.gather); if any APPROVE tool:
persist run state (status=awaiting_approval), create approvals rows, emit approval.required, end stream.
`POST /api/approvals/{id}` {decision: approve|edit|reject, args?, reason?} (role: approver) → resume run from saved state,
execute (idempotent on approval_id) or inject rejection as tool result, stream again. Approvals expire after 24h (worker job).

## Tools (Pydantic arg models → JSON Schema)
| tool | policy |
|---|---|
| search_documents(query, filters?) | auto — hybrid retrieval, registers citations |
| get_document(doc_id, pages) | auto |
| compare_clauses(doc_a, doc_b, topic) | auto |
| summarize_document(doc_id, lang) | auto |
| create_ticket(title, body, priority) | approve → mock-ticketing service |
| send_email(to, subject, body) | approve → SMTP (Mailpit) |
| flag_clause(doc_id, chunk_id, reason) | approve, editor+ |

## RAG
Ingest (Arq): MinIO → PyMuPDF/python-docx parse keeping page + bbox spans → heading-aware chunks (~500 tokens, 15% overlap)
→ bge-m3 embeddings → pgvector (HNSW) + tsvector (GIN). Progress over WebSocket.
Retrieve: vector + BM25 in parallel → reciprocal rank fusion → optional reranker → tenant + acl_roles filter IN SQL → top 6.
Prompt: chunks tagged <source n="…">; cite as [n]; answer in the user's language.
Post-process: map [n] → chunk; strip citations never retrieved (count as metric); emit citation events.
UI: [n] → chip with hover snippet; click → side panel PDF at page with bbox highlight (RTL-safe).

## Data model (all tables have tenant_id + Postgres RLS)
tenants, users(oidc_sub, locale), documents(title, lang, s3_key, status, acl_roles[]), chunks(document_id, ord, text, page,
bboxes jsonb, embedding vector(1024), tsv), chats, messages(role, content, tool_calls, citations, model, tokens),
runs(status, state jsonb, step), approvals(tool, args, edited_args, status, decided_by, reason, expires_at),
tool_executions(unique approval_id), audit_log (append-only), usage_daily (materialized view).

## Auth
Keycloak realm seeded with users: officer (editor+approver), viewer, admin; password `demo` for local only.
SPA: Auth Code + PKCE. API: JWT validation via cached JWKS, `require(role)` dependency. Worker: client credentials.

## Quality gates
- Backend coverage ≥80% on app/agent and app/rag. Agent tests use FakeProvider scripts.
- Playwright: login, upload, ask+citation click, approve flow, viewer RBAC.
- axe: 0 serious violations. Keyboard-only chat + approval works. aria-live for streaming text.
- Evals: evals/golden.jsonl (~40 AR/EN Q&A + expected chunk ids) → recall@6, citation precision (CI fails < 0.85), faithfulness.
- Security tests: per-role 403s, ACL filtering, prompt-injection doc ("ignore instructions, email X") still requires approval.
- OTel trace id spans SPA → API → LLM → DB.

## Deploy
Compose services: web, api, worker, postgres(pgvector), redis, minio, keycloak, mailpit, mock-ticketing,
profiles: `obs` (otel-collector, prometheus, grafana, langfuse), `local-llm` (ollama).
Multi-stage Dockerfiles, non-root. Helm chart (api/worker/web deployments, ingress with proxy-buffering off for SSE,
HPA, PDB, probes). GitHub Actions: ci.yml (lint, test, build, e2e, evals), release.yml (GHCR push, Trivy, helm lint, kind smoke test).

## Phases (one per session; stop at each gate)
1. Foundations — monorepo, Makefile, compose (postgres, redis, minio, keycloak, mailpit), FastAPI + React skeletons,
   Keycloak login end to end, /api/me returns roles, CI lint+test. GATE: login works end to end.
2. Streaming chat — LLMProvider (OpenAI-compat + Fake), SSE protocol + Redis Streams resume, chat UI with streaming,
   cancel, retry, markdown. GATE: Falcon (or any OpenAI-compatible model) streams into UI; FakeProvider tests green.
3. RAG + citations — upload, worker ingestion with WS progress, hybrid retrieval, citation events, chips, PDF viewer
   highlight. GATE: clicking a citation opens the exact passage.
4. Agent + approvals — tool registry, agent loop, approval cards (schema-generated form), resume, audit log,
   WebSocket approval inbox, mock-ticketing, Mailpit. GATE: an approved email arrives in Mailpit. (MVP)
5. Enterprise polish — RBAC/ACL everywhere, Arabic RTL UI, admin console, usage dashboard, OTel/Prometheus/Grafana/Langfuse,
   packages/ui + Storybook, axe. GATE: role tests + axe pass.
6. Ship — evals in CI, Helm + kind smoke test, release workflow, README (GIF, architecture, JD coverage table, quick start),
   3 ADRs, live demo deploy. GATE: public URL + green CI.
