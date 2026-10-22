import { describe, expect, it, vi } from "vitest";

import { ApiError, apiGet } from "./api";

function respond(status: number, body: unknown) {
  return vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(body), { status }));
}

describe("apiGet", () => {
  it("sends the bearer token and returns the body", async () => {
    const fetchImpl = respond(200, { ok: true });
    await expect(apiGet("/api/me", "tok", fetchImpl)).resolves.toEqual({ ok: true });
    const init = fetchImpl.mock.calls[0]?.[1];
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer tok");
  });

  it("turns an ErrorEnvelope into a typed ApiError", async () => {
    const fetchImpl = respond(403, { code: "forbidden", message: "Requires one of: admin.", retryable: false });
    const error = await apiGet("/api/admin/ping", "tok", fetchImpl).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 403, code: "forbidden", retryable: false });
  });

  it("handles non-envelope failures", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502 }));
    await expect(apiGet("/api/me", "tok", fetchImpl)).rejects.toMatchObject({
      code: "http_error",
      retryable: true,
    });
  });
});
