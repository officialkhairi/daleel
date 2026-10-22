/** A server-sent event as parsed from a fetch() body. EventSource can't be used: it only does GET
 * and can't send an Authorization header. */
export interface SseEvent {
  id: string | undefined;
  event: string;
  data: string;
}

function parseBlock(block: string): SseEvent | null {
  let id: string | undefined;
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line === "" || line.startsWith(":")) continue; // comments carry heartbeats
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "id") id = value;
    else if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length === 0 ? null : { id, event, data: data.join("\n") };
}

/** Yields events as they complete. Chunks may split anywhere, including inside a UTF-8 sequence. */
export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let pendingCr = ""; // a "\r" at a chunk's end may be the first half of "\r\n"
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      let text = pendingCr + decoder.decode(value, { stream: true });
      pendingCr = text.endsWith("\r") ? "\r" : "";
      if (pendingCr) text = text.slice(0, -1);
      buffer += text.replace(/\r\n?/g, "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const parsed = parseBlock(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        if (parsed) yield parsed;
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}
