import { useEffect, useState } from "react";

/** Two pages don't need a router library: the path lives in history, and links push to it. */
const NAVIGATE = "daleel:navigate";

export function navigate(path: string): void {
  if (window.location.pathname + window.location.search === path) return;
  window.history.pushState(null, "", path);
  window.dispatchEvent(new Event(NAVIGATE));
}

export function usePathname(): string {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const update = () => {
      setPath(window.location.pathname);
    };
    window.addEventListener("popstate", update);
    window.addEventListener(NAVIGATE, update);
    return () => {
      window.removeEventListener("popstate", update);
      window.removeEventListener(NAVIGATE, update);
    };
  }, []);
  return path;
}
