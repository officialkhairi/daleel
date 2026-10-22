import { ApiError } from "../../lib/api";
import { readSse, type SseEvent } from "../../lib/sse";

/** The SSE protocol from docs/PLAN.md. Every run ends with exactly one `run.completed`. */
export type RunEvent =
  | { type: "run.started"; run_id: string; model: string }
  | { type: "token"; text: string }
  | { type: "usage"; tokens_in: number; tokens_out: number; cost_usd: number }
  | { type: "error"; code: string; message: string; retryable: boolean }
  | { type: "run.completed"; message_id: string | null; finish_reason: string };

const KNOWN = new Set<RunEvent["type"]>(["run.started", "token", "usage", "error", "run.completed"]);

function toRunEvent(sse: SseEvent): RunEvent | null {
  if (!KNOWN.has(sse.event as RunEvent["type"])) return null; // forward-compatible: skip unknown events
  const data = JSON.parse(sse.data) as Record<string, unknown>;
  return { ...data, type: sse.event } as RunEvent;
}

export class StreamLostError extends Error {
  constructor() {
    super("Lost connection to the answer stream.");
    this.name = "StreamLostError";
  }
}

export interface FollowOptions {
  /** First connection: POST a message, POST a retry, or GET a run's events from the start. */
  open: () => Promise<Response>;
  /** Reconnect to a run after a drop, continuing after the last event seen. */
  resume: (runId: string, lastEventId: string | undefined) => Promise<Response>;
  onEvent: (event: RunEvent) => void;
  /** Called before each reconnect attempt (1-based). */
  onReconnect?: (attempt: number) => void;
  signal: AbortSignal;
  maxReconnects?: number;
  wait?: (attempt: number, signal: AbortSignal) => Promise<void>;
}

function backoff(attempt: number, signal: AbortSignal): Promise<void> {
  const ms = Math.min(500 * 2 ** (attempt - 1), 8000);
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(signal.reason as Error);
      },
      { once: true },
    );
  });
}

/** Reads a run's events until `run.completed`, reconnecting with backoff + Last-Event-ID when the
 * connection drops. HTTP errors (ApiError) and aborts are not retried. */
export async function followRun(options: FollowOptions): Promise<void> {
  const { open, resume, onEvent, onReconnect, signal, maxReconnects = 5, wait = backoff } = options;
  let runId: string | undefined;
  let lastEventId: string | undefined;
  let attempt = 0;
  let connect: () => Promise<Response> = open;

  for (;;) {
    try {
      const response = await connect();
      if (!response.body) throw new StreamLostError();
      for await (const sse of readSse(response.body)) {
        lastEventId = sse.id ?? lastEventId;
        const event = toRunEvent(sse);
        if (!event) continue;
        attempt = 0; // progress resets the backoff
        if (event.type === "run.started") runId = event.run_id;
        onEvent(event);
        if (event.type === "run.completed") return;
      }
    } catch (error) {
      if (signal.aborted || error instanceof ApiError) throw error;
      // Network failure: fall through and reconnect.
    }
    if (runId === undefined || attempt >= maxReconnects) throw new StreamLostError();
    attempt += 1;
    onReconnect?.(attempt);
    await wait(attempt, signal);
    const id = runId;
    const after = lastEventId;
    connect = () => resume(id, after);
  }
}
