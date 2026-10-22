import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { User, UserManagerEvents } from "oidc-client-ts";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { AuthProvider, type AuthManager } from "./features/auth/AuthProvider";
import { setLanguage } from "./i18n";
import { fetchRouter, json, sse, sseResponse } from "./test/fetchRouter";

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
  window.history.replaceState(null, "", "/");
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

  it("shows the user's roles in the profile dialog", async () => {
    vi.stubGlobal(
      "fetch",
      fetchRouter({
        "GET /api/me": () =>
          json({
            id: "1",
            sub: "s",
            username: "viewer",
            name: "Read-only Viewer",
            email: null,
            locale: "ar",
            tenant: "acme",
            roles: ["viewer"],
          }),
        "GET /api/chats": () => json([]),
      }),
    );
    renderApp(fakeManager({ access_token: "tok", expired: false } as User));

    await userEvent.click(await screen.findByRole("button", { name: "Read-only Viewer" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Viewer")).toBeInTheDocument();
  });

  it("streams an answer into a new chat", async () => {
    const chat = { id: "c1", title: "", created_at: "", updated_at: "" };
    const saved = {
      chat: { ...chat, title: "Hello" },
      messages: [
        { id: "m1", role: "user", content: "Hello", status: "complete", model: null, tokens_in: null, tokens_out: null, created_at: "" },
        { id: "m2", role: "assistant", content: "**Hi** there", status: "complete", model: "fake", tokens_in: 1, tokens_out: 2, created_at: "" },
      ],
      active_run_id: null,
    };
    const fetchMock = fetchRouter({
      "GET /api/me": () => json({ id: "1", sub: "s", username: "u", name: null, email: null, locale: "en", tenant: "acme", roles: ["viewer"] }),
      "GET /api/chats": () => json([]),
      "POST /api/chats": () => json(chat, 201),
      "POST /api/chats/c1/messages": () =>
        sseResponse([
          sse("1-0", "run.started", { run_id: "r1", model: "fake" }),
          sse("2-0", "token", { text: "**Hi**" }),
          sse("3-0", "token", { text: " there" }),
          sse("4-0", "run.completed", { message_id: "m2", finish_reason: "stop" }),
        ]),
      "GET /api/chats/c1": () => json(saved),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderApp(fakeManager({ access_token: "tok", expired: false } as User));

    await userEvent.type(await screen.findByRole("textbox", { name: "Message" }), "Hello{Enter}");

    const transcript = await screen.findByRole("list", { name: "Conversation" });
    expect(await within(transcript).findByText("Hi", { selector: "strong" })).toBeInTheDocument();
    expect(within(transcript).getByText("Hello")).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([url]) => url === "/api/chats/c1/messages");
    expect(JSON.parse(post?.[1]?.body as string)).toEqual({ content: "Hello" });
    expect(new URLSearchParams(window.location.search).get("chat")).toBe("c1");
  });
});
