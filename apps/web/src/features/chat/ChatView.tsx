import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import type { ChatMessage } from "./api";
import { Composer } from "./Composer";
import { Markdown } from "./Markdown";
import type { RunState } from "./useChatRun";

interface ChatViewProps {
  messages: ChatMessage[];
  run: RunState;
  onSend: (content: string) => void;
  onStop: () => void;
  onRetry: () => void;
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

function AssistantMessage({ content, status, busy }: { content: string; status: ChatMessage["status"]; busy?: boolean }) {
  const { t } = useTranslation();
  return (
    <li>
      <span className="sr-only">{t("chat.assistant")}: </span>
      {/* dir="auto" puts the margin rule on the side the answer's own script starts from, whatever
          the UI language; it must contain only the answer, or the label above would decide it.
          aria-busy holds the live announcement until the answer is complete. */}
      <div
        dir="auto"
        className="border-s-2 border-brand ps-4"
        aria-live={busy ? "polite" : undefined}
        aria-busy={busy}
      >
        <Markdown text={content} />
        {busy && <span className="ms-0.5 inline-block h-4 w-2 animate-pulse bg-brand align-middle" aria-hidden />}
      </div>
      {status === "cancelled" && <p className="mt-1 text-sm text-muted">{t("chat.stopped")}</p>}
    </li>
  );
}

export function ChatView({ messages, run, onSend, onStop, onRetry }: ChatViewProps) {
  const { t } = useTranslation();
  const end = useRef<HTMLDivElement>(null);
  const last = messages.at(-1);
  // A failed run leaves the question unanswered (or answered partially): offer a retry.
  const canRetry = !run.streaming && last !== undefined && (last.role === "user" || last.status !== "complete");

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
                <AssistantMessage key={m.id} content={m.content} status={m.status} />
              ),
            )}
            {run.question !== null && <UserMessage content={run.question} />}
            {run.streaming && <AssistantMessage content={run.draft} status="complete" busy />}
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
            <button
              type="button"
              onClick={onRetry}
              className="mt-3 rounded-md border border-line px-4 py-2 text-sm font-medium text-ink hover:bg-brand-soft"
            >
              {t("chat.retry")}
            </button>
          )}
        </div>
        <div ref={end} />
      </div>
      <Composer streaming={run.streaming} onSend={onSend} onStop={onStop} />
    </div>
  );
}
