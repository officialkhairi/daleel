import { useQuery } from "@tanstack/react-query";

import { apiGet } from "../../lib/api";
import { useAccessToken } from "../auth/AuthProvider";

export interface ChatSummary {
  id: string;
  /** Empty until the first message names the chat. */
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  status: "complete" | "cancelled" | "error";
  model: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  created_at: string;
}

export interface ChatDetail {
  chat: ChatSummary;
  messages: ChatMessage[];
  /** Set while an answer is generating; follow it via /api/runs/{id}/events. */
  active_run_id: string | null;
}

export const chatKeys = {
  list: ["chats"] as const,
  detail: (id: string) => ["chats", id] as const,
};

export function useChats() {
  const token = useAccessToken();
  return useQuery({ queryKey: chatKeys.list, queryFn: () => apiGet<ChatSummary[]>("/api/chats", token) });
}

export function useChat(chatId: string | null) {
  const token = useAccessToken();
  return useQuery({
    queryKey: chatKeys.detail(chatId ?? "none"),
    queryFn: () => apiGet<ChatDetail>(`/api/chats/${chatId ?? ""}`, token),
    enabled: chatId !== null,
  });
}
