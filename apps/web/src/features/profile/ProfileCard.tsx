import { useTranslation } from "react-i18next";

import type { Me } from "./useMe";

export function ProfileCard({ me }: { me: Me }) {
  const { t } = useTranslation();
  const language = me.locale === "ar" || me.locale === "en" ? t(`languages.${me.locale}`) : me.locale;

  return (
    <section aria-labelledby="profile-name" className="border-s-4 border-brand bg-surface px-6 py-6 sm:px-8">
      <h2 id="profile-name" className="text-2xl font-semibold text-ink">
        {me.name ?? me.username}
      </h2>
      <dl className="mt-6 grid gap-x-8 gap-y-4 sm:grid-cols-[max-content_1fr]">
        {me.email && (
          <>
            <dt className="text-sm text-muted">{t("profile.email")}</dt>
            <dd className="text-ink">
              <bdi dir="ltr">{me.email}</bdi>
            </dd>
          </>
        )}
        <dt className="text-sm text-muted">{t("profile.organisation")}</dt>
        <dd className="text-ink">{me.tenant}</dd>
        <dt className="text-sm text-muted">{t("profile.language")}</dt>
        <dd className="text-ink">{language}</dd>
        <dt className="text-sm text-muted">{t("profile.roles")}</dt>
        <dd>
          {me.roles.length > 0 ? (
            <ul className="flex flex-wrap gap-2" aria-label={t("profile.roles")}>
              {me.roles.map((role) => (
                <li key={role} className="rounded-full bg-brand-soft px-3 py-1 text-sm font-medium text-brand">
                  {t(`roles.${role}`)}
                </li>
              ))}
            </ul>
          ) : (
            <span className="text-muted">{t("profile.noRoles")}</span>
          )}
        </dd>
      </dl>
    </section>
  );
}
