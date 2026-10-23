import { useTranslation } from "react-i18next";

import { navigate } from "../../lib/router";
import { usePendingApprovals } from "./api";
import { ApprovalCard } from "./ApprovalCard";

export function ApprovalsPage() {
  const { t, i18n } = useTranslation();
  const approvals = usePendingApprovals(true);
  const time = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" });

  return (
    <main id="main" tabIndex={-1} className="min-h-0 flex-1 overflow-y-auto focus:outline-none">
      <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-8 sm:px-8">
        <div>
          <h1 className="text-2xl font-semibold text-ink">{t("approvals.heading")}</h1>
          <p className="mt-1 text-muted">{t("approvals.lead")}</p>
        </div>
        {approvals.isError && (
          <p role="alert" className="text-danger">
            {approvals.error.message}
          </p>
        )}
        {approvals.data?.length === 0 && <p className="text-muted">{t("approvals.empty")}</p>}
        {approvals.data?.map((approval) => (
          <ApprovalCard
            key={approval.id}
            approval={approval}
            canDecide
            context={
              <>
                {t("approvals.requested", {
                  name: approval.requested_by_name ?? "—",
                  when: time.format(new Date(approval.created_at)),
                })}{" "}
                <a
                  href={`/?chat=${approval.chat_id}`}
                  onClick={(e) => {
                    e.preventDefault();
                    navigate(`/?chat=${approval.chat_id}`);
                  }}
                  className="text-brand underline"
                  dir="auto"
                >
                  {approval.chat_title || t("chat.untitled")}
                </a>
                {" · "}
                {t("approvals.expires", { when: time.format(new Date(approval.expires_at)) })}
              </>
            }
          />
        ))}
      </div>
    </main>
  );
}
