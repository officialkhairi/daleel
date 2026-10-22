import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ChatMessage } from "./api";
import { ChatView } from "./ChatView";
import type { RunState } from "./useChatRun";

const idle: RunState = { streaming: false, runId: null, question: null, draft: "", reconnecting: false, error: null };

function message(role: ChatMessage["role"], content: string, status: ChatMessage["status"] = "complete"): ChatMessage {
  return { id: `${role}-${content}`, role, content, status, model: null, tokens_in: null, tokens_out: null, created_at: "" };
}

function renderView(messages: ChatMessage[], run: RunState = idle) {
  const handlers = { onSend: vi.fn(), onStop: vi.fn(), onRetry: vi.fn() };
  render(<ChatView messages={messages} run={run} {...handlers} />);
  return handlers;
}

describe("ChatView", () => {
  it("shows the empty state and sends on Enter, not Shift+Enter", async () => {
    const { onSend } = renderView([]);
    expect(screen.getByRole("heading", { name: "Ask a question" })).toBeInTheDocument();
    const box = screen.getByRole("textbox", { name: "Message" });
    await userEvent.type(box, "line one{Shift>}{Enter}{/Shift}line two");
    expect(onSend).not.toHaveBeenCalled();
    await userEvent.type(box, "{Enter}");
    expect(onSend).toHaveBeenCalledWith("line one\nline two");
    expect(box).toHaveValue("");
  });

  it("marks the streaming answer busy and offers Stop", async () => {
    const { onStop } = renderView([], { ...idle, streaming: true, runId: "r1", question: "Q?", draft: "Partial" });
    expect(screen.getByText("Q?")).toBeInTheDocument();
    expect(screen.getByText("Partial").closest("[aria-busy]")).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("offers a retry after a failed answer and shows why", async () => {
    const { onRetry } = renderView([message("user", "Q?")], {
      ...idle,
      error: { code: "llm_unavailable", message: "Model server is unreachable.", retryable: true },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Model server is unreachable.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("labels a stopped answer and renders Markdown without raw HTML", () => {
    renderView([message("user", "Q?"), message("assistant", "**bold** <img src=x onerror=alert(1)>", "cancelled")]);
    expect(screen.getByText("bold", { selector: "strong" })).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText("Stopped")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("does not offer a retry after a complete answer", () => {
    renderView([message("user", "Q?"), message("assistant", "A.")]);
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });
});
