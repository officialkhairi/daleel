import type { ReactNode } from "react";

import { cx } from "./cx";

export type BadgeTone = "neutral" | "brand" | "warning" | "danger";

const TONES: Record<BadgeTone, string> = {
  neutral: "bg-line text-ink",
  brand: "bg-brand-soft text-brand",
  warning: "bg-[var(--color-focus)]/20 text-ink",
  danger: "bg-danger/15 text-danger",
};

/** A short label. Tone adds emphasis; the words always carry the meaning. */
export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: ReactNode }) {
  return <span className={cx("rounded px-2 py-0.5 text-xs font-medium", TONES[tone])}>{children}</span>;
}
