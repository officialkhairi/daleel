import { vi } from "vitest";

type Handler = (init: RequestInit | undefined) => Response | Promise<Response>;

/** A fetch stub keyed by "METHOD /path". Unmatched requests fail the test loudly. */
export function fetchRouter(routes: Record<string, Handler>) {
  return vi.fn<typeof fetch>((input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
    const key = `${init?.method ?? "GET"} ${url}`;
    const handler = routes[key];
    if (!handler) return Promise.reject(new Error(`unexpected fetch: ${key}`));
    return Promise.resolve(handler(init));
  });
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** An SSE response whose chunks arrive one at a time; `release()` lets the next chunk through. */
export function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

export function sse(id: string, event: string, data: unknown): string {
  return `id: ${id}\nevent: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}
