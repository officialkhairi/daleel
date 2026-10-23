import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { UserManagerEvents } from "oidc-client-ts";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchRouter, json } from "../../test/fetchRouter";
import { AuthProvider, useAuth, type AuthManager } from "../auth/AuthProvider";
import { ApprovalCard } from "./ApprovalCard";
import type { ApprovalView } from "./types";

const schema = {
  type: "object",
  properties: {
    to: { type: "array", items: { type: "string", format: "email" }, minItems: 1, maxItems: 10 },
    subject: { type: "string", maxLength: 200 },
    body: { type: "string", maxLength: 10000 },
  },
  required: ["to", "subject", "body"],
};

const approval: ApprovalView = {
  id: "a1",
  tool: "send_email",
  args: { to: ["procurement@acme.example"], subject: "Reminder", body: "Contracts above 500,000 AED…" },
  json_schema: schema,
  risk: "high",
  status: "pending",
  expires_at: "2026-10-24T00:00:00Z",
};

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

function Ready({ children }: { children: React.ReactNode }) {
  return useAuth().state.status === "signedIn" ? <>{children}</> : null;
}

function renderCard(view: ApprovalView, canDecide: boolean, onDecided = vi.fn()) {
  const fetchMock = fetchRouter({
    "POST /api/approvals/a1": (init) => {
      const body = JSON.parse(init?.body as string) as { decision: string };
      return json({
        approval: { ...view, status: body.decision === "reject" ? "rejected" : "approved", chat_id: "c1" },
        resumed: true,
        run_id: "r1",
        resume_from: "5-0",
      });
    },
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <AuthProvider manager={manager()}>
      <QueryClientProvider client={new QueryClient()}>
        <Ready>
          <ApprovalCard approval={view} canDecide={canDecide} onDecided={onDecided} />
        </Ready>
      </QueryClientProvider>
    </AuthProvider>,
  );
  return { fetchMock, onDecided };
}

function sentBody(fetchMock: ReturnType<typeof fetchRouter>): unknown {
  return JSON.parse(fetchMock.mock.calls.at(-1)?.[1]?.body as string);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ApprovalCard", () => {
  it("shows the proposed email as a form generated from its schema", async () => {
    renderCard(approval, true);
    expect(await screen.findByRole("heading", { name: "Send an email" })).toBeInTheDocument();
    expect(screen.getByText("High risk")).toBeInTheDocument();
    expect(screen.getByLabelText("To")).toHaveValue("procurement@acme.example");
    expect(screen.getByLabelText("Message").tagName).toBe("TEXTAREA");
    expect(screen.getByText("Needs your approval")).toBeInTheDocument();
  });

  it("approves as-is, or sends the edits", async () => {
    const { fetchMock, onDecided } = renderCard(approval, true);
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect(sentBody(fetchMock)).toEqual({ decision: "approve" });
    expect(onDecided).toHaveBeenCalledWith(expect.objectContaining({ resumed: true, resume_from: "5-0" }));

    const subject = screen.getByLabelText("Subject");
    await userEvent.clear(subject);
    await userEvent.type(subject, "Updated");
    await userEvent.clear(screen.getByLabelText("To"));
    await userEvent.type(screen.getByLabelText("To"), "a@acme.example, b@acme.example");
    await userEvent.click(screen.getByRole("button", { name: "Approve with edits" }));
    expect(sentBody(fetchMock)).toEqual({
      decision: "edit",
      args: { ...approval.args, subject: "Updated", to: ["a@acme.example", "b@acme.example"] },
    });
  });

  it("rejects with a reason", async () => {
    const { fetchMock } = renderCard(approval, true);
    await userEvent.type(await screen.findByLabelText(/Note/), "Wrong recipient");
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(sentBody(fetchMock)).toEqual({ decision: "reject", reason: "Wrong recipient" });
  });

  it("is read-only for people who can't approve", async () => {
    renderCard(approval, false);
    expect(await screen.findByText("Waiting for an approver")).toBeInTheDocument();
    expect(screen.getByLabelText("Subject")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("shows who decided", async () => {
    renderCard(
      { ...approval, status: "approved", decided_by_name: "Compliance Officer", edited_args: { ...approval.args, subject: "X" } },
      true,
    );
    expect(await screen.findByText("Approved with edits by Compliance Officer")).toBeInTheDocument();
    expect(screen.getByLabelText("Subject")).toHaveValue("X");
    expect(screen.queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument();
  });
});
