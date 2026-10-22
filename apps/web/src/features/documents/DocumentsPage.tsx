import * as AlertDialog from "@radix-ui/react-alert-dialog";
import { useId, useRef, useState, type DragEvent, type SyntheticEvent } from "react";
import { useTranslation } from "react-i18next";

import { useMe } from "../profile/useMe";
import { ROLES, useDeleteDocument, useDocuments, useUpload, type DocumentInfo, type Role } from "./api";
import { useDocumentProgress } from "./useDocumentProgress";

const ACCEPT = ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function formatSize(bytes: number, locale: string): string {
  const units = ["byte", "kilobyte", "megabyte"] as const;
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return new Intl.NumberFormat(locale, {
    style: "unit",
    unit: units[unit],
    unitDisplay: "short",
    maximumFractionDigits: unit === 0 ? 0 : 1,
  }).format(value);
}

function UploadCard() {
  const { t } = useTranslation();
  const upload = useUpload();
  const inputId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [roles, setRoles] = useState<Role[]>(ROLES);
  const [dragging, setDragging] = useState(false);

  const choose = (chosen: File | undefined) => {
    if (chosen) {
      setFile(chosen);
      upload.reset();
    }
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    choose(event.dataTransfer.files[0]);
  };

  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    if (!file) return;
    upload.mutate(
      { file, title, roles },
      {
        onSuccess: () => {
          setFile(null);
          setTitle("");
          if (input.current) input.current.value = "";
        },
      },
    );
  };

  const toggle = (role: Role) => {
    setRoles((current) => (current.includes(role) ? current.filter((r) => r !== role) : [...current, role]));
  };

  return (
    <form onSubmit={submit} className="border-s-4 border-brand bg-surface px-6 py-5" aria-labelledby="upload-heading">
      <h2 id="upload-heading" className="text-lg font-semibold text-ink">
        {t("documents.uploadHeading")}
      </h2>
      <label
        htmlFor={inputId}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => {
          setDragging(false);
        }}
        onDrop={onDrop}
        className={`mt-4 flex cursor-pointer flex-col items-center justify-center rounded-md border-2 border-dashed px-4 py-6 text-center ${
          dragging ? "border-brand bg-brand-soft" : "border-line"
        }`}
      >
        <span className="text-ink" dir="auto">
          {file ? file.name : t("documents.dropHint")}
        </span>
        <span className="mt-1 text-sm text-muted">{t("documents.fileTypes")}</span>
        <input
          ref={input}
          id={inputId}
          type="file"
          accept={ACCEPT}
          className="sr-only"
          onChange={(e) => {
            choose(e.target.files?.[0]);
          }}
        />
      </label>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm text-muted">
          {t("documents.titleLabel")}
          <input
            value={title}
            dir="auto"
            maxLength={300}
            onChange={(e) => {
              setTitle(e.target.value);
            }}
            placeholder={t("documents.titlePlaceholder")}
            className="rounded-md border border-line bg-paper px-3 py-2 text-base text-ink"
          />
        </label>
        <fieldset className="text-sm">
          <legend className="text-muted">{t("documents.accessLabel")}</legend>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-2">
            {ROLES.map((role) => (
              <label key={role} className="flex items-center gap-2 text-ink">
                <input
                  type="checkbox"
                  checked={role === "admin" || roles.includes(role)}
                  disabled={role === "admin"}
                  onChange={() => {
                    toggle(role);
                  }}
                  className="size-4 accent-[var(--color-brand)]"
                />
                {t(`roles.${role}`)}
              </label>
            ))}
          </div>
          <p className="mt-1 text-xs text-muted">{t("documents.adminAlways")}</p>
        </fieldset>
      </div>

      {upload.isError && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {upload.error.message}
        </p>
      )}
      <button
        type="submit"
        disabled={!file || upload.isPending}
        className="mt-4 rounded-md bg-brand px-4 py-2 font-medium text-brand-ink hover:opacity-90 disabled:opacity-40"
      >
        {upload.isPending ? t("documents.uploading") : t("documents.upload")}
      </button>
    </form>
  );
}

function Status({ document }: { document: DocumentInfo }) {
  const { t } = useTranslation();
  if (document.status === "ready") return <span className="text-ink">{t("documents.status.ready")}</span>;
  if (document.status === "failed") {
    return (
      <span className="text-danger">
        {t("documents.status.failed")}
        {document.error && <span className="block text-xs">{document.error}</span>}
      </span>
    );
  }
  const label = document.status === "uploaded" ? t("documents.status.queued") : t("documents.status.processing");
  return (
    <span className="flex min-w-32 flex-col gap-1">
      <span className="text-muted">{label}</span>
      <span
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={document.progress}
        className="h-1.5 w-full overflow-hidden rounded-full bg-brand-soft"
      >
        <span className="block h-full bg-brand transition-[width]" style={{ width: `${document.progress}%` }} />
      </span>
    </span>
  );
}

function DeleteButton({ document }: { document: DocumentInfo }) {
  const { t } = useTranslation();
  const remove = useDeleteDocument();
  return (
    <AlertDialog.Root>
      <AlertDialog.Trigger asChild>
        <button type="button" className="rounded-md px-2 py-1 text-sm text-danger hover:bg-brand-soft">
          {t("documents.delete")}
          <span className="sr-only"> {document.title}</span>
        </button>
      </AlertDialog.Trigger>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 bg-ink/40" />
        <AlertDialog.Content className="fixed inset-x-4 top-24 mx-auto max-w-md rounded-lg bg-surface p-6 shadow-lg">
          <AlertDialog.Title className="text-lg font-semibold text-ink" dir="auto">
            {t("documents.deleteTitle", { title: document.title })}
          </AlertDialog.Title>
          <AlertDialog.Description className="mt-2 text-muted">{t("documents.deleteBody")}</AlertDialog.Description>
          <div className="mt-6 flex justify-end gap-2">
            <AlertDialog.Cancel asChild>
              <button type="button" className="rounded-md border border-line px-4 py-2 text-ink hover:bg-brand-soft">
                {t("documents.cancel")}
              </button>
            </AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <button
                type="button"
                onClick={() => {
                  remove.mutate(document.id);
                }}
                className="rounded-md bg-danger px-4 py-2 font-medium text-surface hover:opacity-90"
              >
                {t("documents.delete")}
              </button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}

export function DocumentsPage() {
  const { t, i18n } = useTranslation();
  const me = useMe();
  const documents = useDocuments();
  useDocumentProgress();
  const canEdit = me.data?.roles.some((r) => r === "editor" || r === "admin") ?? false;

  return (
    <main className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-5xl flex-col gap-8 px-4 py-8 sm:px-8">
        <div>
          <h1 className="text-2xl font-semibold text-ink">{t("documents.heading")}</h1>
          <p className="mt-1 text-muted">{t("documents.lead")}</p>
        </div>
        {canEdit && <UploadCard />}

        {documents.isError && (
          <p role="alert" className="text-danger">
            {t("documents.loadFailed", { message: documents.error.message })}
          </p>
        )}
        {documents.data?.length === 0 && <p className="text-muted">{t("documents.empty")}</p>}
        {documents.data && documents.data.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-start text-sm">
              <caption className="sr-only">{t("documents.heading")}</caption>
              <thead className="border-b border-line text-muted">
                <tr>
                  <th scope="col" className="py-2 pe-4 text-start font-medium">
                    {t("documents.columns.title")}
                  </th>
                  <th scope="col" className="py-2 pe-4 text-start font-medium">
                    {t("documents.columns.status")}
                  </th>
                  <th scope="col" className="py-2 pe-4 text-start font-medium">
                    {t("documents.columns.details")}
                  </th>
                  <th scope="col" className="py-2 pe-4 text-start font-medium">
                    {t("documents.columns.access")}
                  </th>
                  {canEdit && (
                    <th scope="col" className="py-2 text-start font-medium">
                      <span className="sr-only">{t("documents.columns.actions")}</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {documents.data.map((d) => (
                  <tr key={d.id} className="border-b border-line align-top">
                    <td className="py-3 pe-4">
                      <span className="font-medium text-ink" dir="auto">
                        {d.title}
                      </span>
                      <span className="block text-xs text-muted" dir="ltr">
                        {d.filename}
                      </span>
                    </td>
                    <td className="py-3 pe-4">
                      <Status document={d} />
                    </td>
                    <td className="py-3 pe-4 text-muted">
                      {[
                        d.lang ? t(`languages.${d.lang === "ar" ? "ar" : "en"}`) : null,
                        d.page_count !== null ? t("documents.pages", { count: d.page_count }) : null,
                        formatSize(d.size_bytes, i18n.language),
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </td>
                    <td className="py-3 pe-4 text-muted">
                      {d.acl_roles.length === ROLES.length
                        ? t("documents.everyone")
                        : new Intl.ListFormat(i18n.language, { type: "unit" }).format(
                            d.acl_roles.map((r) => t(`roles.${r}`)),
                          )}
                    </td>
                    {canEdit && (
                      <td className="py-3">
                        <DeleteButton document={d} />
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}
