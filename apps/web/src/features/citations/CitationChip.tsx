import * as Tooltip from "@radix-ui/react-tooltip";
import { useTranslation } from "react-i18next";

import type { Citation } from "./types";

export function CitationChip({ citation, onOpen }: { citation: Citation; onOpen: (c: Citation) => void }) {
  const { t } = useTranslation();
  const where =
    citation.page === null ? citation.title : t("citations.titlePage", { title: citation.title, page: citation.page });
  return (
    <Tooltip.Root delayDuration={200}>
      <Tooltip.Trigger asChild>
        <button
          type="button"
          onClick={() => {
            onOpen(citation);
          }}
          aria-label={t("citations.open", { n: citation.n, where })}
          className="mx-0.5 inline-flex min-w-5 items-center justify-center rounded bg-brand-soft px-1 align-baseline text-xs font-semibold text-brand hover:bg-brand hover:text-brand-ink"
        >
          {citation.n}
        </button>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          side="top"
          sideOffset={6}
          className="z-50 max-w-sm rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink shadow-lg"
        >
          <p className="font-medium" dir="auto">
            {where}
          </p>
          <p className="mt-1 text-muted" dir="auto">
            {citation.snippet}
          </p>
          <Tooltip.Arrow className="fill-[var(--color-surface)]" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}
