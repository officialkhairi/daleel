import { useTranslation } from "react-i18next";

import { LanguageToggle } from "../../LanguageToggle";
import { useAuth } from "./AuthProvider";

export function SignInScreen() {
  const { t } = useTranslation();
  const { state, signIn } = useAuth();
  const failed = state.status === "signedOut" && state.error === "signInFailed";

  return (
    <div className="flex min-h-dvh flex-col">
      <div className="flex justify-end px-4 pt-4 sm:px-8">
        <LanguageToggle />
      </div>
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-4 pb-24 sm:px-8">
        <h1 className="border-s-4 border-brand ps-6">
          <span lang="ar" className="block text-7xl font-semibold leading-tight text-brand sm:text-8xl">
            دليل
          </span>
          <span lang="en" className="mt-1 block text-2xl font-medium tracking-wide text-ink">
            Daleel
          </span>
        </h1>
        <p className="mt-8 max-w-[52ch] text-lg leading-relaxed text-muted">{t("signIn.lead")}</p>
        {failed && (
          <p role="alert" className="mt-6 text-danger">
            {t("signIn.failed")}
          </p>
        )}
        <div className="mt-10">
          <button
            type="button"
            onClick={() => void signIn()}
            className="rounded-md bg-brand px-6 py-3 text-base font-medium text-brand-ink hover:opacity-90"
          >
            {t("signIn.button")}
          </button>
        </div>
      </main>
    </div>
  );
}
