import { Button } from "@daleel/ui";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { ApprovalCard } from "../approvals/ApprovalCard";
import type { ApprovalView, DecisionOut } from "../approvals/types";
import type { Citation } from "../citations/types";
import type { ChatMessage } from "./api";
import { Composer } from "./Composer";
import { Markdown } from "./Markdown";
import { ToolSteps, type StepView } from "./ToolSteps";
import type { RunState } from "./useChatRun";

interface ChatViewProps {
  messages: ChatMessage[];
  run: RunState;
  onSend: (content: string) => void;
  onStop: () => void;
  onRetry: () => void;
  onCite: (citation: Citation) => void;
  /** Saved approvals of this chat, by id. */
  approvals?: Map<string, ApprovalView>;
  canDecide?: boolean;
  onDecided?: (result: DecisionOut) => void;
}

function UserMessage({ content }: { content: string }) {
  const { t } = useTranslation();
  return (
    <li className="flex justify-end">
      <div className="max-w-[85%] rounded-lg bg-brand-soft px-4 py-2.5 text-ink">
        <span className="sr-only">{t("chat.you")}: </span>
        <p dir="auto" className="whitespace-pre-wrap">
          {content}
        </p>
      </div>
    </li>
  );
}

interface AssistantMessageProps {
  content: string;
  status: ChatMessage["status"];
  citations: Citation[];
  onCite: (citation: Citation) => void;
  steps?: StepView[];
  approvals?: ApprovalView[];
  canDecide?: boolean;
  onDecided?: ((result: DecisionOut) => void) | undefined;
  busy?: boolean;
}

function AssistantMessage({
  content,
  status,
  citations,
  onCite,
  steps = [],
  approvals = [],
  canDecide = false,
  onDecided,
  busy,
}: AssistantMessageProps) {
  const { t } = useTranslation();
  return (
    <li>
      <span className="sr-only">{t("chat.assistant")}: </span>
      <ToolSteps steps={steps} />
      {/* dir="auto" puts the margin rule on the side the answer's own script starts from, whatever
          the UI language; it must contain only the answer, or the label above would decide it.
          aria-busy holds the live announcement until the answer is complete. */}
      <div
        dir="auto"
        className="border-s-2 border-brand ps-4"
        aria-live={busy ? "polite" : undefined}
        aria-busy={busy}
      >
        {(content || busy) && <Markdown text={content} citations={citations} onCite={onCite} />}
        {busy && <span className="ms-0.5 inline-block h-4 w-2 animate-pulse bg-brand align-middle" aria-hidden />}
      </div>
      {status === "cancelled" && <p className="mt-1 text-sm text-muted">{t("chat.stopped")}</p>}
      {approvals.map((approval) => (
        <div key={approval.id} className="mt-3">
          <ApprovalCard approval={approval} canDecide={canDecide} onDecided={onDecided} />
        </div>
      ))}
    </li>
  );
}

const TOOLS_NEEDING_APPROVAL = new Set(["send_email", "create_ticket", "flag_clause"]);

/** Calls that waited for approval are shown by their approval card, not as a step. */
function savedSteps(message: ChatMessage): StepView[] {
  return (message.tool_calls ?? [])
    .filter((call) => !call.approval_id)
    .map((call) => ({ callId: call.call_id, tool: call.tool, summary: call.summary, ok: call.ok, data: call.data }));
}

export function ChatView({
  messages,
  run,
  onSend,
  onStop,
  onRetry,
  onCite,
  approvals = new Map(),
  canDecide = false,
  onDecided,
}: ChatViewProps) {
  const { t } = useTranslation();
  const end = useRef<HTMLDivElement>(null);
  const last = messages.at(-1);
  // A failed run leaves the question unanswered (or answered partially): offer a retry. A paused
  // answer waiting for an approval isn't a failure.
  const waiting = (last?.tool_calls ?? []).some((c) => c.approval_id && approvals.get(c.approval_id)?.status === "pending");
  const canRetry =
    !run.streaming && !waiting && last !== undefined && (last.role === "user" || last.status !== "complete");

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [messages.length, run.draft, run.question]);

  const empty = messages.length === 0 && !run.question;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-8 sm:px-8">
        {empty ? (
          <div className="mx-auto mt-16 max-w-xl">
            <h2 className="text-2xl font-semibold text-ink">{t("chat.emptyTitle")}</h2>
            <p className="mt-2 text-muted">{t("chat.emptyBody")}</p>
          </div>
        ) : (
          <ol className="mx-auto flex max-w-3xl flex-col gap-6" aria-label={t("chat.transcript")}>
            {messages.map((m) =>
              m.role === "user" ? (
                <UserMessage key={m.id} content={m.content} />
              ) : (
                <AssistantMessage
                  key={m.id}
                  content={m.content}
                  status={m.status}
                  citations={m.citations ?? []}
                  onCite={onCite}
                  steps={savedSteps(m)}
                  approvals={(m.tool_calls ?? []).flatMap((call) => {
                    const approval = call.approval_id ? approvals.get(call.approval_id) : undefined;
                    return approval ? [approval] : [];
                  })}
                  canDecide={canDecide}
                  onDecided={onDecided}
                />
              ),
            )}
            {run.question !== null && <UserMessage content={run.question} />}
            {run.streaming && (
              <AssistantMessage
                content={run.draft}
                status="complete"
                citations={run.citations}
                onCite={onCite}
                steps={run.steps.filter(
                  (step) => step.summary !== undefined || !TOOLS_NEEDING_APPROVAL.has(step.tool),
                )}
                approvals={run.approvals}
                canDecide={canDecide}
                onDecided={onDecided}
                busy
              />
            )}
          </ol>
        )}
        <div className="mx-auto max-w-3xl">
          {run.reconnecting && (
            <p role="status" className="mt-4 text-sm text-muted">
              {t("chat.reconnecting")}
            </p>
          )}
          {run.error && !run.streaming && (
            <div role="alert" className="mt-6 border-s-2 border-danger ps-4 text-danger">
              <p>{t("chat.answerFailed", { message: run.error.message })}</p>
            </div>
          )}
          {canRetry && (
            <Button size="sm" className="mt-3" onClick={onRetry}>
              {t("chat.retry")}
            </Button>
          )}
        </div>
        <div ref={end} />
      </div>
      <Composer streaming={run.streaming} onSend={onSend} onStop={onStop} />
    </div>
  );
}
