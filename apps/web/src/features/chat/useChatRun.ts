import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, apiRequest } from "../../lib/api";
import { useAccessToken } from "../auth/AuthProvider";
import { chatKeys } from "./api";
import { followRun, type RunEvent } from "./stream";

export interface RunError {
  code: string;
  message: string;
  retryable: boolean;
}

export interface RunState {
  streaming: boolean;
  runId: string | null;
  /** The question being answered, shown until the saved messages are refetched. */
  question: string | null;
  draft: string;
  reconnecting: boolean;
  error: RunError | null;
}

const IDLE: RunState = {
  streaming: false,
  runId: null,
  question: null,
  draft: "",
  reconnecting: false,
  error: null,
};

const SSE_HEADERS = { Accept: "text/event-stream" };

function toRunError(error: unknown): RunError {
  if (error instanceof ApiError) return { code: error.code, message: error.message, retryable: error.retryable };
  return { code: "stream_lost", message: error instanceof Error ? error.message : String(error), retryable: true };
}

/** Streams one answer at a time for a chat. Leaving the chat stops reading but not the run:
 * the server keeps generating and the chat resumes it (active_run_id) when reopened. */
export function useChatRun(chatId: string | null) {
  const token = useAccessToken();
  const tokenRef = useRef(token);
  useEffect(() => {
    tokenRef.current = token;
  }, [token]);
  const queryClient = useQueryClient();
  const [state, setState] = useState<RunState>(IDLE);
  const controller = useRef<AbortController | null>(null);
  // Which chat the current stream belongs to. Sending the first message creates the chat and
  // selects it, and that selection must not abort the stream that is just starting.
  const streamChat = useRef<string | null>(null);

  useEffect(() => {
    if (streamChat.current !== chatId) {
      controller.current?.abort();
      streamChat.current = null;
      setState(IDLE);
    }
  }, [chatId]);

  useEffect(() => () => controller.current?.abort(), []);

  const run = useCallback(
    async (id: string, open: (signal: AbortSignal) => Promise<Response>, question: string | null) => {
      controller.current?.abort();
      const abort = new AbortController();
      controller.current = abort;
      streamChat.current = id;
      setState({ ...IDLE, streaming: true, question });

      const onEvent = (event: RunEvent) => {
        setState((s) => {
          switch (event.type) {
            case "run.started":
              return { ...s, runId: event.run_id, reconnecting: false };
            case "token":
              return { ...s, draft: s.draft + event.text, reconnecting: false };
            case "error":
              return { ...s, error: { code: event.code, message: event.message, retryable: event.retryable } };
            default:
              return s;
          }
        });
      };

      try {
        await followRun({
          open: () => open(abort.signal),
          resume: (runId, lastEventId) =>
            apiRequest(`/api/runs/${runId}/events`, tokenRef.current, {
              headers: { ...SSE_HEADERS, ...(lastEventId ? { "Last-Event-ID": lastEventId } : {}) },
              signal: abort.signal,
            }),
          onEvent,
          onReconnect: () => {
            setState((s) => ({ ...s, reconnecting: true }));
          },
          signal: abort.signal,
        });
      } catch (error) {
        if (abort.signal.aborted) return;
        setState((s) => ({ ...s, error: toRunError(error) }));
      }
      // The saved messages replace the draft once they are refetched.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: chatKeys.detail(id) }),
        queryClient.invalidateQueries({ queryKey: chatKeys.list }),
      ]);
      if (!abort.signal.aborted) {
        setState((s) => ({ ...IDLE, error: s.error }));
      }
    },
    [queryClient],
  );

  const send = useCallback(
    (id: string, content: string) =>
      run(
        id,
        (signal) =>
          apiRequest(`/api/chats/${id}/messages`, tokenRef.current, {
            method: "POST",
            body: { content },
            headers: SSE_HEADERS,
            signal,
          }),
        content,
      ),
    [run],
  );

  const retry = useCallback(
    (id: string) =>
      run(
        id,
        (signal) =>
          apiRequest(`/api/chats/${id}/retry`, tokenRef.current, { method: "POST", headers: SSE_HEADERS, signal }),
        null,
      ),
    [run],
  );

  /** Picks up a run that was already generating when the chat was opened. */
  const follow = useCallback(
    (id: string, runId: string) =>
      run(
        id,
        (signal) => apiRequest(`/api/runs/${runId}/events`, tokenRef.current, { headers: SSE_HEADERS, signal }),
        null,
      ),
    [run],
  );

  /** Asks the server to stop; the stream then ends with finish_reason "cancelled". */
  const stop = useCallback(async () => {
    if (!state.runId) {
      controller.current?.abort();
      setState(IDLE);
      return;
    }
    try {
      await apiRequest(`/api/runs/${state.runId}/cancel`, tokenRef.current, { method: "POST" });
    } catch {
      controller.current?.abort();
      setState(IDLE);
    }
  }, [state.runId]);

  return { state, send, retry, follow, stop };
}
