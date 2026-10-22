import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { apiPost } from "../../lib/api";
import { useAccessToken } from "../auth/AuthProvider";
import { chatKeys, useChat, useChats, type ChatSummary } from "./api";
import { ChatView } from "./ChatView";
import { useChatRun } from "./useChatRun";
import { useSelectedChat } from "./useSelectedChat";

function ChatList({ selected, onSelect }: { selected: string | null; onSelect: (id: string | null) => void }) {
  const { t } = useTranslation();
  const chats = useChats();
  return (
    <nav aria-label={t("chat.history")} className="flex min-h-0 flex-col border-line md:w-64 md:border-e">
      <div className="p-3">
        <button
          type="button"
          onClick={() => {
            onSelect(null);
          }}
          className="w-full rounded-md border border-line px-3 py-2 text-start text-sm font-medium text-ink hover:bg-brand-soft"
        >
          {t("chat.newChat")}
        </button>
      </div>
      <ul className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:overflow-y-auto">
        {chats.data?.length === 0 && <li className="px-2 text-sm text-muted">{t("chat.noChats")}</li>}
        {chats.data?.map((chat: ChatSummary) => (
          <li key={chat.id} className="shrink-0">
            <button
              type="button"
              onClick={() => {
                onSelect(chat.id);
              }}
              aria-current={chat.id === selected ? "page" : undefined}
              dir="auto"
              className="w-full max-w-60 truncate rounded-md px-3 py-2 text-start text-sm text-ink hover:bg-brand-soft aria-[current=page]:bg-brand-soft aria-[current=page]:font-medium"
            >
              {chat.title || t("chat.untitled")}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function ChatPage() {
  const { t } = useTranslation();
  const token = useAccessToken();
  const queryClient = useQueryClient();
  const [chatId, select] = useSelectedChat();
  const chat = useChat(chatId);
  const { state, send, retry, follow, stop } = useChatRun(chatId);

  // Reopening a chat whose answer is still generating picks the stream back up.
  const followed = useRef<string | null>(null);
  const activeRun = chat.data?.active_run_id ?? null;
  useEffect(() => {
    if (chatId && activeRun && !state.streaming && followed.current !== activeRun) {
      followed.current = activeRun;
      void follow(chatId, activeRun);
    }
  }, [chatId, activeRun, state.streaming, follow]);

  const onSend = async (content: string) => {
    let id = chatId;
    if (id === null) {
      const created = await apiPost<ChatSummary>("/api/chats", token);
      queryClient.setQueryData(chatKeys.detail(created.id), { chat: created, messages: [], active_run_id: null });
      select(created.id);
      id = created.id;
    }
    await send(id, content);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col md:flex-row">
      <ChatList selected={chatId} onSelect={select} />
      <main className="flex min-h-0 flex-1 flex-col">
        {chat.isError ? (
          <p role="alert" className="p-8 text-danger">
            {t("chat.loadFailed", { message: chat.error.message })}
          </p>
        ) : (
          <ChatView
            messages={chat.data?.messages ?? []}
            run={state}
            onSend={(content) => void onSend(content)}
            onStop={() => void stop()}
            onRetry={() => {
              if (chatId) void retry(chatId);
            }}
          />
        )}
      </main>
    </div>
  );
}
