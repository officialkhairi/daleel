import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useDecide } from "./api";
import { changes, SchemaForm, type FormValues } from "./SchemaForm";
import type { ApprovalView, DecisionOut } from "./types";

interface ApprovalCardProps {
  approval: ApprovalView;
  /** Shown to approvers; others see the request and its state. The API decides either way. */
  canDecide: boolean;
  onDecided?: ((result: DecisionOut) => void) | undefined;
  context?: React.ReactNode;
}

const RISK_STYLE = {
  low: "bg-brand-soft text-brand",
  medium: "bg-[var(--color-focus)]/20 text-ink",
  high: "bg-danger/15 text-danger",
} as const;

export function ApprovalCard({ approval, canDecide, onDecided, context }: ApprovalCardProps) {
  const { t } = useTranslation();
  const decide = useDecide();
  const original = approval.edited_args ?? approval.args;
  const [values, setValues] = useState<FormValues>(original);
  const [reason, setReason] = useState("");
  const pending = approval.status === "pending";
  const editable = pending && canDecide;
  const edited = changes(approval.args, values);

  const submit = (decision: "approve" | "reject") => {
    decide.mutate(
      {
        approvalId: approval.id,
        decision: decision === "approve" && edited ? "edit" : decision,
        ...(decision === "approve" && edited ? { args: edited } : {}),
        ...(reason.trim() ? { reason: reason.trim() } : {}),
      },
      { onSuccess: (result) => onDecided?.(result) },
    );
  };

  const statusLine = (() => {
    const name = approval.decided_by_name ?? "";
    switch (approval.status) {
      case "approved":
        return approval.edited_args ? t("approvals.status.edited", { name }) : t("approvals.status.approved", { name });
      case "rejected":
        return t("approvals.status.rejected", { name });
      case "expired":
        return approval.reason ?? t("approvals.status.expired");
      default:
        return canDecide ? t("approvals.status.needsYou") : t("approvals.status.waiting");
    }
  })();

  return (
    <section
      aria-label={t("approvals.cardLabel", { action: t(`tools.${approval.tool}.propose`) })}
      className={`rounded-lg border bg-surface p-4 ${pending ? "border-[var(--color-focus)]" : "border-line"}`}
    >
      <header className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold text-ink">{t(`tools.${approval.tool}.propose`)}</h3>
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${RISK_STYLE[approval.risk]}`}>
          {t(`approvals.risk.${approval.risk}`)}
        </span>
        <span className="ms-auto text-sm text-muted" role={pending ? undefined : "status"}>
          {statusLine}
        </span>
      </header>
      {context && <div className="mt-1 text-sm text-muted">{context}</div>}

      <div className="mt-4">
        <SchemaForm schema={approval.json_schema} values={values} onChange={setValues} readOnly={!editable} />
      </div>

      {approval.status === "rejected" && approval.reason && (
        <p className="mt-3 text-sm text-muted" dir="auto">
          {t("approvals.reasonGiven", { reason: approval.reason })}
        </p>
      )}

      {editable && (
        <div className="mt-4 grid gap-3">
          <label className="grid gap-1 text-sm text-muted">
            {t("approvals.reasonLabel")}
            <input
              value={reason}
              dir="auto"
              maxLength={1000}
              onChange={(e) => {
                setReason(e.target.value);
              }}
              className="rounded-md border border-line bg-paper px-3 py-2 text-ink"
            />
          </label>
          {decide.isError && (
            <p role="alert" className="text-sm text-danger">
              {decide.error.message}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={decide.isPending}
              onClick={() => {
                submit("approve");
              }}
              className="rounded-md bg-brand px-4 py-2 font-medium text-brand-ink hover:opacity-90 disabled:opacity-40"
            >
              {edited ? t("approvals.approveEdited") : t("approvals.approve")}
            </button>
            <button
              type="button"
              disabled={decide.isPending}
              onClick={() => {
                submit("reject");
              }}
              className="rounded-md border border-line px-4 py-2 font-medium text-danger hover:bg-brand-soft disabled:opacity-40"
            >
              {t("approvals.reject")}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
