import * as Tooltip from "@radix-ui/react-tooltip";
import type { MouseEvent, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "./features/auth/AuthProvider";
import { SignInScreen } from "./features/auth/SignInScreen";
import { ChatPage } from "./features/chat/ChatPage";
import { DocumentsPage } from "./features/documents/DocumentsPage";
import { ProfileDialog } from "./features/profile/ProfileDialog";
import { LanguageToggle } from "./LanguageToggle";
import { navigate, usePathname } from "./lib/router";

function Loading() {
  const { t } = useTranslation();
  return (
    <p role="status" className="p-8 text-muted">
      {t("status.loading")}
    </p>
  );
}

function NavLink({ href, current, children }: { href: string; current: boolean; children: ReactNode }) {
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    navigate(href);
  };
  return (
    <a
      href={href}
      onClick={onClick}
      aria-current={current ? "page" : undefined}
      className="rounded-md px-3 py-1.5 text-sm font-medium text-muted hover:bg-brand-soft aria-[current=page]:bg-brand-soft aria-[current=page]:text-ink"
    >
      {children}
    </a>
  );
}

function Shell() {
  const { t } = useTranslation();
  const { signOut } = useAuth();
  const path = usePathname();
  const onDocuments = path.startsWith("/documents");
  return (
    <div className="flex h-dvh flex-col">
      <header className="border-b border-line bg-surface">
        <div className="flex items-center gap-4 px-4 py-3 sm:px-6">
          <span className="flex items-baseline gap-2 text-lg font-semibold text-brand">
            <span lang="ar">دليل</span>
            <span lang="en" className="text-ink">
              Daleel
            </span>
          </span>
          <nav aria-label={t("nav.label")} className="flex items-center gap-1">
            <NavLink href="/" current={!onDocuments}>
              {t("nav.chat")}
            </NavLink>
            <NavLink href="/documents" current={onDocuments}>
              {t("nav.documents")}
            </NavLink>
          </nav>
          <div className="ms-auto flex items-center gap-2">
            <LanguageToggle />
            <ProfileDialog />
            <button
              type="button"
              onClick={() => void signOut()}
              className="rounded-md border border-line px-3 py-1.5 text-sm font-medium text-ink hover:bg-brand-soft"
            >
              {t("header.signOut")}
            </button>
          </div>
        </div>
      </header>
      {onDocuments ? <DocumentsPage /> : <ChatPage />}
    </div>
  );
}

export function App() {
  const { state } = useAuth();
  if (state.status === "loading") return <Loading />;
  if (state.status === "signedOut") return <SignInScreen />;
  return (
    <Tooltip.Provider>
      <Shell />
    </Tooltip.Provider>
  );
}
