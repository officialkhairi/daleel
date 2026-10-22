import { useCallback, useEffect, useState } from "react";

const PARAM = "chat";

function read(): string | null {
  return new URLSearchParams(window.location.search).get(PARAM);
}

/** The open chat lives in the URL (?chat=<id>) so reloads and back/forward keep it. */
export function useSelectedChat(): [string | null, (id: string | null) => void] {
  const [chatId, setChatId] = useState<string | null>(read);

  useEffect(() => {
    const onPop = () => {
      setChatId(read());
    };
    window.addEventListener("popstate", onPop);
    return () => {
      window.removeEventListener("popstate", onPop);
    };
  }, []);

  const select = useCallback((id: string | null) => {
    const url = new URL(window.location.href);
    if (id) url.searchParams.set(PARAM, id);
    else url.searchParams.delete(PARAM);
    window.history.pushState(null, "", url);
    setChatId(id);
  }, []);

  return [chatId, select];
}
