import { useTranslation } from "react-i18next";

import { setLanguage } from "./i18n";

export function LanguageToggle() {
  const { t, i18n } = useTranslation();
  const next = i18n.language === "ar" ? "en" : "ar";
  return (
    <button
      type="button"
      onClick={() => {
        setLanguage(next);
      }}
      aria-label={t("header.switchLanguage")}
      lang={next}
      className="rounded-md px-3 py-1.5 text-sm font-medium text-ink hover:bg-brand-soft"
    >
      {t("header.otherLanguage")}
    </button>
  );
}
