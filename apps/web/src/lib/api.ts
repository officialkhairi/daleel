export interface ErrorEnvelope {
  code: string;
  message: string;
  retryable: boolean;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly retryable: boolean,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return typeof v.code === "string" && typeof v.message === "string" && typeof v.retryable === "boolean";
}

/** GET a JSON resource from the API with the caller's access token. Non-2xx responses throw ApiError. */
export async function apiGet<T>(path: string, token: string, fetchImpl: typeof fetch = fetch): Promise<T> {
  const response = await fetchImpl(path, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    if (isErrorEnvelope(body)) {
      throw new ApiError(response.status, body.code, body.message, body.retryable);
    }
    throw new ApiError(response.status, "http_error", `Request failed (${response.status})`, response.status >= 500);
  }
  return body as T;
}
