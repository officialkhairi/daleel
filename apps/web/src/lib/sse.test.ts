import { describe, expect, it } from "vitest";

import { readSse, type SseEvent } from "./sse";

function streamOf(chunks: (string | Uint8Array)[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(typeof chunk === "string" ? encoder.encode(chunk) : chunk);
      controller.close();
    },
  });
}

async function collect(chunks: (string | Uint8Array)[]): Promise<SseEvent[]> {
  const events: SseEvent[] = [];
  for await (const event of readSse(streamOf(chunks))) events.push(event);
  return events;
}

describe("readSse", () => {
  it("parses id, event and data", async () => {
    expect(await collect(['id: 1-0\nevent: token\ndata: {"text":"hi"}\n\n'])).toEqual([
      { id: "1-0", event: "token", data: '{"text":"hi"}' },
    ]);
  });

  it("handles events split across chunks at any point", async () => {
    const raw = "id: 1-0\nevent: token\ndata: one\n\nid: 2-0\nevent: token\ndata: two\n\n";
    for (let cut = 1; cut < raw.length; cut++) {
      const events = await collect([raw.slice(0, cut), raw.slice(cut)]);
      expect(events.map((e) => e.data)).toEqual(["one", "two"]);
    }
  });

  it("decodes UTF-8 split inside a character", async () => {
    const bytes = new TextEncoder().encode("data: مرحبا\n\n");
    const events = await collect([bytes.slice(0, 8), bytes.slice(8)]);
    expect(events[0]?.data).toBe("مرحبا");
  });

  it("accepts CRLF line endings, even split between chunks", async () => {
    expect(await collect(["event: a\r", "\ndata: x\r\n\r", "\n"])).toEqual([{ id: undefined, event: "a", data: "x" }]);
  });

  it("skips heartbeats and joins multi-line data", async () => {
    expect(await collect([": ping\n\n", "data: line 1\ndata: line 2\n\n"])).toEqual([
      { id: undefined, event: "message", data: "line 1\nline 2" },
    ]);
  });

  it("drops an incomplete trailing event", async () => {
    expect(await collect(["data: done\n\ndata: cut off"])).toHaveLength(1);
  });
});
