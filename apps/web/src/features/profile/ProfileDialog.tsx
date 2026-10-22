import * as Dialog from "@radix-ui/react-dialog";
import { useTranslation } from "react-i18next";

import { ProfileCard } from "./ProfileCard";
import { useMe } from "./useMe";

export function ProfileDialog() {
  const { t } = useTranslation();
  const me = useMe();
  const label = me.data ? (me.data.name ?? me.data.username) : t("header.profile");

  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>
        <button
          type="button"
          className="max-w-48 truncate rounded-md px-3 py-1.5 text-sm font-medium text-ink hover:bg-brand-soft"
        >
          {label}
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-ink/40" />
        <Dialog.Content className="fixed inset-x-4 top-20 mx-auto max-w-lg rounded-lg bg-surface shadow-lg focus:outline-none">
          <Dialog.Title className="sr-only">{t("profile.title")}</Dialog.Title>
          <Dialog.Description className="sr-only">{t("profile.description")}</Dialog.Description>
          {me.isPending && <p className="p-6 text-muted">{t("status.loading")}</p>}
          {me.isError && (
            <p role="alert" className="p-6 text-danger">
              {t("profile.loadFailed", { message: me.error.message })}
            </p>
          )}
          {me.data && <ProfileCard me={me.data} />}
          <div className="flex justify-end px-6 pb-4">
            <Dialog.Close asChild>
              <button type="button" className="rounded-md border border-line px-4 py-2 text-sm text-ink hover:bg-brand-soft">
                {t("profile.close")}
              </button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
