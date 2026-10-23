# ADR 0004: Human approval for every side effect, enforced in code

- Status: accepted
- Date: 2026-10-23

## Context

The assistant reads untrusted text (uploaded documents, chat history) and can call tools that act outside
Daleel: sending email, opening tickets, flagging clauses. A model can be talked into anything by text it reads
(prompt injection), and even a well-behaved model makes mistakes. People also need to see and correct what will
be sent before it is sent.

## Decision

- **Tools carry a fixed policy** (`auto` or `approve`), a risk level and allowed roles, declared next to their
  Pydantic argument models. The agent loop consults only this registry; nothing in a prompt or document can
  change a tool's policy.
- **Side effects pause the run.** The run's state is saved in Postgres, one approval row per proposed call is
  created, and the stream ends. Only a person with the approver (or admin) role can decide, via the API, which
  checks the role server-side.
- **Approvers can edit.** The approval form is generated from the tool's JSON Schema; edited arguments are
  validated by the same model as the agent's.
- **Execution is idempotent per approval** (a unique execution row claimed before acting), so retries and
  restarts never repeat an email.
- **Everything is audited** in an append-only table enforced by the database.

## Alternatives considered

- **Trusting the model to ask for confirmation.** Fails exactly when it matters: an injected instruction can also
  say "don't ask".
- **Confirming in the chat stream only (no persisted state).** Breaks when the approver is a different person or
  decides hours later.
- **Approval in an external workflow tool.** Heavier, and splits the record of what the assistant did from the
  conversation that caused it.

## Consequences

- Runs can be paused for up to 24 hours; their state lives in `runs.state`, and expiry is a scheduled job.
- The model sees rejections as tool results and can explain or adjust; it never sees an effect it wasn't
  allowed to cause.
- Adding a tool means choosing its policy deliberately; the default is not `auto`.
