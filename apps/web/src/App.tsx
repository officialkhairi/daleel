import { useTranslation } from "react-i18next";

import { useAuth } from "./features/auth/AuthProvider";
import { SignInScreen } from "./features/auth/SignInScreen";
import { ChatPage } from "./features/chat/ChatPage";
import { ProfileDialog } from "./features/profile/ProfileDialog";
import { LanguageToggle } from "./LanguageToggle";

function Loading() {
  const { t } = useTranslation();
  return (
    <p role="status" className="p-8 text-muted">
      {t("status.loading")}
    </p>
  );
}

function Shell() {
  const { t } = useTranslation();
  const { signOut } = useAuth();
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
      <ChatPage />
    </div>
  );
}

export function App() {
  const { state } = useAuth();
  if (state.status === "loading") return <Loading />;
  if (state.status === "signedOut") return <SignInScreen />;
  return <Shell />;
}
