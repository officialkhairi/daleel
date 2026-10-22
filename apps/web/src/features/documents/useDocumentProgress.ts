import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { useAccessToken } from "../auth/AuthProvider";
import { documentKeys, type DocumentInfo } from "./api";

interface ProgressEvent {
  type: "document.progress";
  document_id: string;
  status: DocumentInfo["status"];
  stage: string;
  progress: number;
  error: string | null;
  chunk_count: number | null;
  page_count: number | null;
}

function socketUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/api/ws/documents`;
}

/** Keeps the documents list live while ingestion runs. The token goes in the first message, not
 * the URL. Reconnects with backoff; the server closes the socket when the token expires. */
export function useDocumentProgress(): void {
  const token = useAccessToken();
  const tokenRef = useRef(token);
  const queryClient = useQueryClient();

  useEffect(() => {
    tokenRef.current = token;
  }, [token]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    const apply = (event: ProgressEvent) => {
      const seen = { known: false };
      queryClient.setQueryData<DocumentInfo[]>(documentKeys.list, (list) =>
        list?.map((d) => {
          if (d.id !== event.document_id) return d;
          seen.known = true;
          return {
            ...d,
            status: event.status,
            progress: event.progress,
            error: event.error,
            chunk_count: event.chunk_count ?? d.chunk_count,
            page_count: event.page_count ?? d.page_count,
          };
        }),
      );
      // Someone else uploaded it: fetch the list to pick it up.
      if (!seen.known || event.status === "ready") void queryClient.invalidateQueries({ queryKey: documentKeys.list });
    };

    const connect = () => {
      socket = new WebSocket(socketUrl());
      socket.onopen = () => {
        socket?.send(JSON.stringify({ type: "auth", token: tokenRef.current }));
      };
      socket.onmessage = (message: MessageEvent<string>) => {
        const data = JSON.parse(message.data) as { type: string };
        if (data.type === "ready") attempt = 0;
        if (data.type === "document.progress") apply(data as ProgressEvent);
      };
      socket.onclose = () => {
        if (stopped) return;
        attempt += 1;
        timer = setTimeout(connect, Math.min(1000 * 2 ** (attempt - 1), 15000));
      };
    };
    connect();

    return () => {
      stopped = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, [queryClient]);
}
