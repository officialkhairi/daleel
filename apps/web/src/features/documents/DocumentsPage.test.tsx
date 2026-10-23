import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { UserManagerEvents } from "oidc-client-ts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchRouter, json } from "../../test/fetchRouter";
import { AuthProvider, useAuth, type AuthManager } from "../auth/AuthProvider";
import type { DocumentInfo } from "./api";
import { useNotifications } from "../notifications/useNotifications";
import { DocumentsPage } from "./DocumentsPage";

class FakeSocket {
  static last: FakeSocket | null = null;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(readonly url: string) {
    FakeSocket.last = this;
    setTimeout(() => this.onopen?.(), 0);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.onclose = null;
  }
  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

const doc = (over: Partial<DocumentInfo>): DocumentInfo => ({
  id: "d1",
  title: "سياسة المشتريات",
  filename: "procurement.pdf",
  content_type: "application/pdf",
  size_bytes: 36720,
  lang: "ar",
  status: "ready",
  progress: 100,
  error: null,
  page_count: 2,
  chunk_count: 8,
  acl_roles: ["viewer", "editor", "approver", "admin"],
  created_at: "",
  updated_at: "",
  ...over,
});

function manager(): AuthManager {
  const noop = () => () => undefined;
  return {
    getUser: vi.fn().mockResolvedValue({ access_token: "tok", expired: false }),
    signinRedirect: vi.fn(),
    signinRedirectCallback: vi.fn(),
    signoutRedirect: vi.fn(),
    removeUser: vi.fn(),
    events: new Proxy({}, { get: () => noop }) as unknown as UserManagerEvents,
  };
}

function Page() {
  useNotifications(); // mounted by the app shell in real use
  return <DocumentsPage />;
}

function SignedIn() {
  return useAuth().state.status === "signedIn" ? <Page /> : null;
}

function renderPage(roles: string[], documents: DocumentInfo[]) {
  vi.stubGlobal(
    "fetch",
    fetchRouter({
      "GET /api/me": () =>
        json({ id: "1", sub: "s", username: "u", name: "U", email: null, locale: "en", tenant: "acme", roles }),
      "GET /api/documents": () => json(documents),
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <AuthProvider manager={manager()}>
      <QueryClientProvider client={client}>
        <SignedIn />
      </QueryClientProvider>
    </AuthProvider>,
  );
}

beforeEach(() => {
  vi.stubGlobal("WebSocket", FakeSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DocumentsPage", () => {
  it("lists documents; viewers get no upload or delete", async () => {
    renderPage(["viewer"], [doc({})]);
    expect(await screen.findByText("سياسة المشتريات")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("Everyone")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Add a document" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete/ })).not.toBeInTheDocument();
  });

  it("editors can upload; admin access can't be unticked", async () => {
    renderPage(["editor"], []);
    expect(await screen.findByRole("heading", { name: "Add a document" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Admin" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
    await userEvent.upload(screen.getByLabelText(/Drop a file here/), new File(["%PDF-"], "policy.pdf"));
    expect(screen.getByRole("button", { name: "Upload" })).toBeEnabled();
  });

  it("shows live progress from the WebSocket after authenticating", async () => {
    renderPage(["viewer"], [doc({ status: "processing", progress: 10, page_count: null })]);
    await screen.findByText("سياسة المشتريات");
    const socket = FakeSocket.last;
    await vi.waitFor(() => {
      expect(socket?.sent[0]).toBe(JSON.stringify({ type: "auth", token: "tok" }));
    });
    act(() => {
      socket?.emit({
        type: "document.progress",
        document_id: "d1",
        status: "processing",
        stage: "embedding",
        progress: 60,
        error: null,
        chunk_count: null,
        page_count: null,
      });
    });
    await vi.waitFor(() => {
      const bar = within(screen.getByRole("table")).getByRole("progressbar");
      expect(bar).toHaveAttribute("aria-valuenow", "60");
    });
  });

  it("explains failures", async () => {
    renderPage(["viewer"], [doc({ status: "failed", error: "No text found." })]);
    expect(await screen.findByText("No text found.")).toBeInTheDocument();
  });
});
