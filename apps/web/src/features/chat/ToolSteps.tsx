import { useTranslation } from "react-i18next";

export interface StepView {
  callId: string;
  tool: string;
  summary?: string | undefined;
  ok?: boolean | undefined;
  data?: Record<string, unknown> | undefined;
}

/** What the assistant did on the way to its answer, one line per tool call. */
export function ToolSteps({ steps }: { steps: StepView[] }) {
  const { t } = useTranslation();
  if (steps.length === 0) return null;
  return (
    <ul aria-label={t("tools.stepsLabel")} className="mb-2 flex flex-col gap-1 text-sm text-muted">
      {steps.map((step) => {
        const running = step.summary === undefined;
        return (
          <li key={step.callId} className="flex items-center gap-2">
            <span
              aria-hidden
              className={`size-2 rounded-full ${
                running ? "animate-pulse bg-[var(--color-focus)]" : step.ok === false ? "bg-danger" : "bg-brand"
              }`}
            />
            <span>{t(`tools.${step.tool}.${running ? "running" : "done"}`, { defaultValue: step.tool })}</span>
            {step.summary && (
              <span className="text-xs" dir="auto">
                ·{" "}
                {step.ok === false
                  ? step.summary
                  : t(`tools.${step.tool}.summary`, { ...step.data, defaultValue: step.summary })}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
