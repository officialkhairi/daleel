import { Button } from "@daleel/ui";
import * as Tooltip from "@radix-ui/react-tooltip";
import type { MouseEvent, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "./features/auth/AuthProvider";
import { SignInScreen } from "./features/auth/SignInScreen";
import { AdminPage } from "./features/admin/AdminPage";
import { usePendingApprovals } from "./features/approvals/api";
import { ApprovalsPage } from "./features/approvals/ApprovalsPage";
import { ChatPage } from "./features/chat/ChatPage";
import { useNotifications } from "./features/notifications/useNotifications";
import { useMe } from "./features/profile/useMe";
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
  const me = useMe();
  useNotifications();
  const isApprover = me.data?.roles.some((r) => r === "approver" || r === "admin") ?? false;
  const pending = usePendingApprovals(isApprover);
  const pendingCount = pending.data?.length ?? 0;
  const isAdmin = me.data?.roles.includes("admin") ?? false;
  const page = path.startsWith("/documents")
    ? "documents"
    : path.startsWith("/approvals") && isApprover
      ? "approvals"
      : path.startsWith("/admin") && isAdmin
        ? "admin"
        : "chat";
  return (
    <div className="flex h-dvh flex-col">
      {/* First stop for keyboard users: past the header and chat list (WCAG 2.4.1). */}
      <a
        href={page === "chat" ? "#composer" : "#main"}
        className="sr-only z-50 rounded-md bg-surface px-4 py-2 text-ink focus:not-sr-only focus:fixed focus:start-4 focus:top-4"
      >
        {page === "chat" ? t("nav.skipToComposer") : t("nav.skipToMain")}
      </a>
      <header className="border-b border-line bg-surface">
        <div className="flex items-center gap-4 px-4 py-3 sm:px-6">
          <span className="flex items-baseline gap-2 text-lg font-semibold text-brand">
            <span lang="ar">دليل</span>
            <span lang="en" className="text-ink">
              Daleel
            </span>
          </span>
          <nav aria-label={t("nav.label")} className="flex items-center gap-1">
            <NavLink href="/" current={page === "chat"}>
              {t("nav.chat")}
            </NavLink>
            <NavLink href="/documents" current={page === "documents"}>
              {t("nav.documents")}
            </NavLink>
            {isApprover && (
              <NavLink href="/approvals" current={page === "approvals"}>
                {t("nav.approvals")}
                {pendingCount > 0 && (
                  <span className="ms-1.5 rounded-full bg-[var(--color-focus)] px-1.5 text-xs text-ink">
                    <span className="sr-only">{t("nav.pendingCount", { count: pendingCount })}</span>
                    <span aria-hidden>{pendingCount}</span>
                  </span>
                )}
              </NavLink>
            )}
            {isAdmin && (
              <NavLink href="/admin" current={page === "admin"}>
                {t("nav.admin")}
              </NavLink>
            )}
          </nav>
          <div className="ms-auto flex items-center gap-2">
            <LanguageToggle />
            <ProfileDialog />
            <Button size="sm" onClick={() => void signOut()}>
              {t("header.signOut")}
            </Button>
          </div>
        </div>
      </header>
      {page === "documents" ? (
        <DocumentsPage />
      ) : page === "approvals" ? (
        <ApprovalsPage />
      ) : page === "admin" ? (
        <AdminPage />
      ) : (
        <ChatPage />
      )}
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
