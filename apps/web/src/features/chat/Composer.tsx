import { useState, type KeyboardEvent, type SyntheticEvent } from "react";
import { useTranslation } from "react-i18next";

interface ComposerProps {
  streaming: boolean;
  onSend: (content: string) => void;
  onStop: () => void;
}

export function Composer({ streaming, onSend, onStop }: ComposerProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const content = value.trim();

  const submit = (event?: SyntheticEvent) => {
    event?.preventDefault();
    if (streaming || !content) return;
    onSend(content);
    setValue("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // IME composition (Arabic keyboards on some platforms) must not submit.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form onSubmit={submit} className="border-t border-line bg-surface px-4 py-3 sm:px-8">
      <div className="mx-auto flex max-w-3xl items-end gap-3">
        <label htmlFor="composer" className="sr-only">
          {t("chat.inputLabel")}
        </label>
        <textarea
          id="composer"
          // Empty, dir="auto" resolves to LTR in Chromium and flips the Arabic placeholder.
          dir={value ? "auto" : undefined}
          rows={2}
          value={value}
          maxLength={8000}
          onChange={(e) => {
            setValue(e.target.value);
          }}
          onKeyDown={onKeyDown}
          placeholder={t("chat.placeholder")}
          aria-describedby="composer-hint"
          className="min-h-12 flex-1 resize-y rounded-md border border-line bg-paper px-3 py-2 text-ink placeholder:text-muted"
        />
        {streaming ? (
          <button
            type="button"
            onClick={onStop}
            className="rounded-md border border-line px-4 py-2.5 font-medium text-ink hover:bg-brand-soft"
          >
            {t("chat.stop")}
          </button>
        ) : (
          <button
            type="submit"
            disabled={!content}
            className="rounded-md bg-brand px-4 py-2.5 font-medium text-brand-ink hover:opacity-90 disabled:opacity-40"
          >
            {t("chat.send")}
          </button>
        )}
      </div>
      <p id="composer-hint" className="mx-auto mt-1 max-w-3xl text-xs text-muted">
        {t("chat.sendHint")}
      </p>
    </form>
  );
}
