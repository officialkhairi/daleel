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

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

/** Sends a request with the caller's access token. Non-2xx responses throw ApiError. */
export async function apiRequest(path: string, token: string, options: RequestOptions = {}): Promise<Response> {
  const { method = "GET", body, headers = {}, signal, fetchImpl = fetch } = options;
  // FormData (uploads) sets its own multipart Content-Type; anything else is sent as JSON.
  const isForm = body instanceof FormData;
  const init: RequestInit = {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json",
      ...(body === undefined || isForm ? {} : { "Content-Type": "application/json" }),
      ...headers,
    },
  };
  if (body !== undefined) init.body = isForm ? body : JSON.stringify(body);
  if (signal) init.signal = signal;

  const response = await fetchImpl(path, init);
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    if (isErrorEnvelope(payload)) {
      throw new ApiError(response.status, payload.code, payload.message, payload.retryable);
    }
    throw new ApiError(response.status, "http_error", `Request failed (${response.status})`, response.status >= 500);
  }
  return response;
}

/** GET a JSON resource from the API with the caller's access token. */
export async function apiGet<T>(path: string, token: string, fetchImpl: typeof fetch = fetch): Promise<T> {
  const response = await apiRequest(path, token, { fetchImpl });
  return (await response.json()) as T;
}

export async function apiPost<T>(path: string, token: string, body: unknown = {}): Promise<T> {
  const response = await apiRequest(path, token, { method: "POST", body });
  return (await response.json()) as T;
}

export async function apiDelete(path: string, token: string): Promise<void> {
  await apiRequest(path, token, { method: "DELETE" });
}
