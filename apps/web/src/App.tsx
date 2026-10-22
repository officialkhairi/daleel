import { useTranslation } from "react-i18next";

import { useAuth } from "./features/auth/AuthProvider";
import { SignInScreen } from "./features/auth/SignInScreen";
import { ProfileCard } from "./features/profile/ProfileCard";
import { useMe } from "./features/profile/useMe";
import { LanguageToggle } from "./LanguageToggle";

function Loading() {
  const { t } = useTranslation();
  return (
    <p role="status" className="p-8 text-muted">
      {t("status.loading")}
    </p>
  );
}

function Profile() {
  const { t } = useTranslation();
  const me = useMe();
  if (me.isPending) return <Loading />;
  if (me.isError) {
    return (
      <div role="alert" className="text-danger">
        <p>{t("profile.loadFailed", { message: me.error.message })}</p>
        <button
          type="button"
          onClick={() => void me.refetch()}
          className="mt-3 rounded-md border border-line px-4 py-2 text-ink hover:bg-brand-soft"
        >
          {t("profile.retry")}
        </button>
      </div>
    );
  }
  return <ProfileCard me={me.data} />;
}

function Shell() {
  const { t } = useTranslation();
  const { signOut } = useAuth();
  return (
    <div className="min-h-dvh">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-5xl items-center gap-4 px-4 py-3 sm:px-8">
          <span className="flex items-baseline gap-2 text-lg font-semibold text-brand">
            <span lang="ar">دليل</span>
            <span lang="en" className="text-ink">
              Daleel
            </span>
          </span>
          <div className="ms-auto flex items-center gap-2">
            <LanguageToggle />
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
      <main className="mx-auto max-w-5xl px-4 py-10 sm:px-8">
        <Profile />
      </main>
    </div>
  );
}

export function App() {
  const { state } = useAuth();
  if (state.status === "loading") return <Loading />;
  if (state.status === "signedOut") return <SignInScreen />;
  return <Shell />;
}
