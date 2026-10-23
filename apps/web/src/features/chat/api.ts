import { useQuery } from "@tanstack/react-query";

import { apiGet } from "../../lib/api";
import { useAccessToken } from "../auth/AuthProvider";
import type { ApprovalOut } from "../approvals/types";
import type { Citation } from "../citations/types";

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
  citations?: Citation[] | null;
  tool_calls?: SavedToolCall[] | null;
  model: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  created_at: string;
}

export interface SavedToolCall {
  call_id: string;
  tool: string;
  args: Record<string, unknown>;
  summary?: string;
  ok?: boolean;
  data?: Record<string, unknown>;
  approval_id?: string;
}

export interface ChatDetail {
  chat: ChatSummary;
  messages: ChatMessage[];
  approvals?: ApprovalOut[];
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
