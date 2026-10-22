# ADR 0002: SSE over fetch, backed by one Redis Stream per run

- Status: accepted
- Date: 2026-10-22

## Context

Answers stream token by token. The connection between the browser and the API will drop: laptops sleep,
proxies time out, users reload. Users also need to stop an answer, and later phases add runs that pause for a
human approval and resume minutes or hours later (Phase 4). The API may run as several replicas.

## Decision

- **Server-sent events, read with `fetch`.** One direction is enough; SSE passes through ordinary HTTP
  infrastructure. `EventSource` is not used because it only does GET and cannot send an `Authorization`
  header, so the SPA has a small hand-written parser over a `ReadableStream`.
- **The run is decoupled from the HTTP response.** Generation runs as a background task that appends every
  event to a Redis Stream (`run:{id}:events`). Every HTTP response, including the one returned by the POST,
  is just a reader of that stream.
- **Stream entry ids are SSE event ids.** `Last-Event-ID` maps directly onto `XREAD` from that id, so resuming
  needs no bookkeeping of our own.
- **Every run ends with exactly one `run.completed`.** Errors are an `error` event before it. Clients have one
  terminal condition to wait for.
- **Cancel is a flag in Redis**, checked by the run every 200 ms, so any replica can accept it.

## Alternatives considered

- **WebSockets.** Bidirectional, but needs its own auth handshake, reconnect protocol and proxy configuration,
  and gives nothing here that SSE lacks. Phase 3/4 use WebSockets only for push notifications (ingestion
  progress, approval inbox).
- **Generating inside the request handler.** Simplest, but a dropped connection would kill the answer, and
  resume or cross-replica cancel would be impossible.
- **Redis pub/sub.** No replay: a reader that connects late or reconnects misses events.

## Consequences

- Redis becomes a hard dependency of chat (it already is for Arq).
- Runs live in API processes for now; a restart ends them with a retryable error. Moving them to the worker
  later does not change the protocol.
- Event history is kept only for `RUN_EVENTS_TTL_SECONDS` (default 1 hour). After that, the saved messages in
  Postgres are the record and the events endpoint returns 410.
