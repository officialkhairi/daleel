import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../../lib/api";
import { sse } from "../../test/fetchRouter";
import { followRun, StreamLostError, type RunEvent } from "./stream";

const encoder = new TextEncoder();

/** A response that sends `chunks` and then either ends cleanly or fails like a dropped connection. */
function response(chunks: string[], { drop = false } = {}): Response {
  const queue = [...chunks];
  // Pull-based: erroring in start() would discard chunks the reader hasn't consumed yet.
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      const next = queue.shift();
      if (next !== undefined) controller.enqueue(encoder.encode(next));
      else if (drop) controller.error(new TypeError("network error"));
      else controller.close();
    },
  });
  return new Response(body);
}

const started = sse("1-0", "run.started", { run_id: "r1", model: "m" });
const token = (id: string, text: string) => sse(id, "token", { text });
const completed = sse("9-0", "run.completed", { message_id: "m1", finish_reason: "stop" });

function follow(open: () => Promise<Response>, resume: (runId: string, last: string | undefined) => Promise<Response>) {
  const events: RunEvent[] = [];
  const onReconnect = vi.fn();
  const promise = followRun({
    open,
    resume,
    onEvent: (e) => events.push(e),
    onReconnect,
    signal: new AbortController().signal,
    wait: () => Promise.resolve(),
  });
  return { events, onReconnect, promise };
}

describe("followRun", () => {
  it("reads until run.completed", async () => {
    const { events, promise } = follow(() => Promise.resolve(response([started, token("2-0", "hi"), completed])), vi.fn());
    await promise;
    expect(events.map((e) => e.type)).toEqual(["run.started", "token", "run.completed"]);
  });

  it("resumes after a drop from the last event id", async () => {
    const resume = vi.fn(() => Promise.resolve(response([token("3-0", " world"), completed])));
    const { events, onReconnect, promise } = follow(
      () => Promise.resolve(response([started, token("2-0", "hello")], { drop: true })),
      resume,
    );
    await promise;
    expect(resume).toHaveBeenCalledWith("r1", "2-0");
    expect(onReconnect).toHaveBeenCalledWith(1);
    const text = events.flatMap((e) => (e.type === "token" ? [e.text] : [])).join("");
    expect(text).toBe("hello world");
  });

  it("treats a stream that ends early as a drop", async () => {
    const resume = vi.fn(() => Promise.resolve(response([completed])));
    await follow(() => Promise.resolve(response([started])), resume).promise;
    expect(resume).toHaveBeenCalledWith("r1", "1-0");
  });

  it("gives up after repeated failures", async () => {
    const resume = vi.fn(() => Promise.reject(new TypeError("offline")));
    const { promise } = follow(() => Promise.resolve(response([started], { drop: true })), resume);
    await expect(promise).rejects.toBeInstanceOf(StreamLostError);
    expect(resume).toHaveBeenCalledTimes(5);
  });

  it("does not retry HTTP errors", async () => {
    const conflict = new ApiError(409, "run_in_progress", "busy", false);
    const resume = vi.fn();
    await expect(follow(() => Promise.reject(conflict), resume).promise).rejects.toBe(conflict);
    expect(resume).not.toHaveBeenCalled();
  });

  it("cannot resume before knowing the run id", async () => {
    const resume = vi.fn();
    await expect(follow(() => Promise.reject(new TypeError("offline")), resume).promise).rejects.toBeInstanceOf(
      StreamLostError,
    );
    expect(resume).not.toHaveBeenCalled();
  });
});
