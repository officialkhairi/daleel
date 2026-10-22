import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { User, UserManagerEvents } from "oidc-client-ts";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { AuthProvider, type AuthManager } from "./features/auth/AuthProvider";
import { setLanguage } from "./i18n";

function fakeManager(user: User | null) {
  const noop = () => () => undefined;
  const events = new Proxy({}, { get: () => noop }) as unknown as UserManagerEvents;
  return {
    getUser: vi.fn().mockResolvedValue(user),
    signinRedirect: vi.fn().mockResolvedValue(undefined),
    signinRedirectCallback: vi.fn(),
    signoutRedirect: vi.fn().mockResolvedValue(undefined),
    removeUser: vi.fn().mockResolvedValue(undefined),
    events,
  } satisfies AuthManager;
}

function renderApp(manager: AuthManager) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <AuthProvider manager={manager}>
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>
    </AuthProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  act(() => {
    setLanguage("en");
  });
});

describe("App", () => {
  it("offers sign-in when there is no session", async () => {
    const manager = fakeManager(null);
    renderApp(manager);
    await userEvent.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(manager.signinRedirect).toHaveBeenCalledOnce();
  });

  it("switches the document to RTL for Arabic", async () => {
    renderApp(fakeManager(null));
    await userEvent.click(await screen.findByRole("button", { name: "Switch language" }));
    expect(document.documentElement).toHaveAttribute("dir", "rtl");
    expect(document.documentElement).toHaveAttribute("lang", "ar");
    expect(screen.getByRole("button", { name: "تسجيل الدخول" })).toBeInTheDocument();
  });

  it("shows the signed-in user's roles from /api/me", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "1",
          sub: "s",
          username: "viewer",
          name: "Read-only Viewer",
          email: null,
          locale: "ar",
          tenant: "acme",
          roles: ["viewer"],
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = { access_token: "tok", expired: false } as User;
    renderApp(fakeManager(user));

    expect(await screen.findByRole("heading", { name: "Read-only Viewer" })).toBeInTheDocument();
    expect(screen.getByText("Viewer")).toBeInTheDocument();
    const init = fetchMock.mock.calls[0]?.[1];
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer tok");
  });

  it("shows the API's error message and a retry button", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(JSON.stringify({ code: "db_unavailable", message: "Database is unavailable.", retryable: true }), {
          status: 503,
        }),
      ),
    );
    renderApp(fakeManager({ access_token: "tok", expired: false } as User));
    expect(await screen.findByRole("alert")).toHaveTextContent("Database is unavailable.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
