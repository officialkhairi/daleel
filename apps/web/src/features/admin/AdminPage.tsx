import { StatTile } from "@daleel/ui";
import * as Tabs from "@radix-ui/react-tabs";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useAudit, useUsage, useUsers, type UsageDay } from "./api";
import { Chart } from "./charts";

const DAYS = 30;

/** One entry per day of the window (UTC), summed across models; days without runs are empty. */
function byDay(rows: UsageDay[], days: number) {
  const out: { day: string; runs: number; failed: number; tokensIn: number; tokensOut: number; cost: number; p50: number | null; p95: number | null }[] = [];
  const today = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - i));
    const key = d.toISOString().slice(0, 10);
    const matching = rows.filter((r) => r.day === key);
    // Percentiles don't add across models; show the worst model's value for the day.
    const p50s = matching.flatMap((r) => (r.ttft_p50_ms === null ? [] : [r.ttft_p50_ms]));
    const p95s = matching.flatMap((r) => (r.ttft_p95_ms === null ? [] : [r.ttft_p95_ms]));
    out.push({
      day: key,
      runs: matching.reduce((s, r) => s + r.runs, 0),
      failed: matching.reduce((s, r) => s + r.failed, 0),
      tokensIn: matching.reduce((s, r) => s + r.tokens_in, 0),
      tokensOut: matching.reduce((s, r) => s + r.tokens_out, 0),
      cost: matching.reduce((s, r) => s + Number(r.cost_usd), 0),
      p50: p50s.length ? Math.max(...p50s) / 1000 : null,
      p95: p95s.length ? Math.max(...p95s) / 1000 : null,
    });
  }
  return out;
}

function UsageTab() {
  const { t, i18n } = useTranslation();
  const usage = useUsage(DAYS);
  const number = new Intl.NumberFormat(i18n.language);
  const compact = new Intl.NumberFormat(i18n.language, { notation: "compact" });
  const money = new Intl.NumberFormat(i18n.language, { style: "currency", currency: "USD", maximumFractionDigits: 4 });
  const seconds = new Intl.NumberFormat(i18n.language, { style: "unit", unit: "second", maximumFractionDigits: 1 });
  const dayLabel = new Intl.DateTimeFormat(i18n.language, { month: "short", day: "numeric", timeZone: "UTC" });

  if (usage.isPending) return <p className="text-muted">{t("status.loading")}</p>;
  if (usage.isError) return <p role="alert" className="text-danger">{usage.error.message}</p>;

  const days = byDay(usage.data.days, DAYS);
  const labels = days.map((d) => dayLabel.format(new Date(`${d.day}T00:00:00Z`)));
  const { totals } = usage.data;
  const runs = days.reduce((s, d) => s + d.runs, 0);
  const failed = days.reduce((s, d) => s + d.failed, 0);
  const cost = days.reduce((s, d) => s + d.cost, 0);

  return (
    <div className="flex flex-col gap-6">
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <StatTile label={t("admin.kpi.questions")} value={number.format(totals.questions)} />
        <StatTile label={t("admin.kpi.documents")} value={number.format(totals.documents)} />
        <StatTile label={t("admin.kpi.users")} value={number.format(totals.users)} />
        <StatTile label={t("admin.kpi.pending")} value={number.format(totals.pending_approvals)} />
        <StatTile
          label={t("admin.kpi.failureRate")}
          value={runs ? `${number.format(Math.round((failed / runs) * 1000) / 10)}%` : "–"}
          hint={t("admin.lastDays", { count: DAYS })}
        />
        <StatTile label={t("admin.kpi.cost")} value={money.format(cost)} hint={t("admin.lastDays", { count: DAYS })} />
      </dl>
      <div className="grid gap-4 xl:grid-cols-2">
        <Chart
          kind="bars"
          title={t("admin.charts.runs")}
          labels={labels}
          format={(v) => number.format(v)}
          series={[
            { key: "ok", label: t("admin.series.answered"), color: "var(--color-brand)", values: days.map((d) => d.runs - d.failed) },
            { key: "failed", label: t("admin.series.failed"), color: "var(--color-danger)", values: days.map((d) => d.failed) },
          ]}
        />
        <Chart
          kind="lines"
          title={t("admin.charts.ttft")}
          labels={labels}
          format={(v) => seconds.format(v)}
          series={[
            { key: "p50", label: "p50", color: "var(--color-series-1)", values: days.map((d) => d.p50) },
            { key: "p95", label: "p95", color: "var(--color-series-2)", values: days.map((d) => d.p95) },
          ]}
        />
        <Chart
          kind="bars"
          title={t("admin.charts.tokens")}
          labels={labels}
          format={(v) => compact.format(v)}
          series={[
            { key: "in", label: t("admin.series.input"), color: "var(--color-series-1)", values: days.map((d) => d.tokensIn) },
            { key: "out", label: t("admin.series.output"), color: "var(--color-series-2)", values: days.map((d) => d.tokensOut) },
          ]}
        />
        <Chart
          kind="bars"
          title={t("admin.charts.cost")}
          labels={labels}
          format={(v) => money.format(v)}
          series={[{ key: "cost", label: t("admin.kpi.cost"), color: "var(--color-brand)", values: days.map((d) => d.cost) }]}
        />
      </div>
    </div>
  );
}

function UsersTab() {
  const { t, i18n } = useTranslation();
  const users = useUsers();
  const time = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" });
  if (users.isPending) return <p className="text-muted">{t("status.loading")}</p>;
  if (users.isError) return <p role="alert" className="text-danger">{users.error.message}</p>;
  return (
    <div className="overflow-x-auto">
      <p className="mb-3 text-sm text-muted">{t("admin.usersNote")}</p>
      <table className="w-full text-start text-sm">
        <caption className="sr-only">{t("admin.tabs.users")}</caption>
        <thead className="border-b border-line text-muted">
          <tr>
            {["name", "email", "roles", "language", "lastSeen"].map((c) => (
              <th key={c} scope="col" className="py-2 pe-4 text-start font-medium">
                {t(`admin.columns.${c}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {users.data.map((u) => (
            <tr key={u.id} className="border-b border-line">
              <td className="py-2 pe-4 text-ink" dir="auto">
                {u.display_name ?? u.username}
              </td>
              <td className="py-2 pe-4 text-muted">
                <bdi dir="ltr">{u.email ?? "–"}</bdi>
              </td>
              <td className="py-2 pe-4 text-ink">
                {new Intl.ListFormat(i18n.language, { type: "unit" }).format(u.roles.map((r) => t(`roles.${r}`)))}
              </td>
              <td className="py-2 pe-4 text-muted">{t(`languages.${u.locale === "ar" ? "ar" : "en"}`)}</td>
              <td className="py-2 pe-4 text-muted">{time.format(new Date(u.last_seen_at))}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const AUDIT_ACTIONS = [
  "approval.requested",
  "approval.approved",
  "approval.edited",
  "approval.rejected",
  "approval.expired",
  "approval.superseded",
  "tool.executed",
  "tool.failed",
  "document.uploaded",
  "document.updated",
  "document.deleted",
];

function AuditTab() {
  const { t, i18n } = useTranslation();
  const [action, setAction] = useState("");
  const entries = useAudit(action);
  const time = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "medium" });
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">{t("admin.auditNote")}</p>
      <label className="flex max-w-sm flex-col gap-1 text-sm text-muted">
        {t("admin.filterAction")}
        <select
          value={action}
          onChange={(e) => {
            setAction(e.target.value);
          }}
          className="rounded-md border border-line bg-paper px-3 py-2 text-ink"
        >
          <option value="">{t("admin.allActions")}</option>
          {AUDIT_ACTIONS.map((a) => (
            <option key={a} value={a}>
              {t(`admin.actions.${a}`, { defaultValue: a })}
            </option>
          ))}
        </select>
      </label>
      {entries.isError && <p role="alert" className="text-danger">{entries.error.message}</p>}
      {entries.data?.length === 0 && <p className="text-muted">{t("admin.auditEmpty")}</p>}
      {entries.data && entries.data.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-start text-sm">
            <caption className="sr-only">{t("admin.tabs.audit")}</caption>
            <thead className="border-b border-line text-muted">
              <tr>
                {["when", "who", "action", "details"].map((c) => (
                  <th key={c} scope="col" className="py-2 pe-4 text-start font-medium">
                    {t(`admin.columns.${c}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {entries.data.map((e) => (
                <tr key={e.id} className="border-b border-line align-top">
                  <td className="whitespace-nowrap py-2 pe-4 text-muted">{time.format(new Date(e.created_at))}</td>
                  <td className="py-2 pe-4 text-ink">{e.actor}</td>
                  <td className="py-2 pe-4 text-ink">{t(`admin.actions.${e.action}`, { defaultValue: e.action })}</td>
                  <td className="py-2 pe-4">
                    <code dir="ltr" className="block max-w-xl truncate text-xs text-muted" title={JSON.stringify(e.details)}>
                      {JSON.stringify(e.details)}
                    </code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function AdminPage() {
  const { t } = useTranslation();
  const tab = "rounded-md px-3 py-1.5 text-sm font-medium text-muted hover:bg-brand-soft data-[state=active]:bg-brand-soft data-[state=active]:text-ink";
  return (
    <main id="main" tabIndex={-1} className="min-h-0 flex-1 overflow-y-auto focus:outline-none">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-8 sm:px-8">
        <h1 className="text-2xl font-semibold text-ink">{t("admin.heading")}</h1>
        <Tabs.Root defaultValue="usage" className="flex flex-col gap-6">
          <Tabs.List aria-label={t("admin.heading")} className="flex gap-1 border-b border-line pb-2">
            <Tabs.Trigger value="usage" className={tab}>
              {t("admin.tabs.usage")}
            </Tabs.Trigger>
            <Tabs.Trigger value="users" className={tab}>
              {t("admin.tabs.users")}
            </Tabs.Trigger>
            <Tabs.Trigger value="audit" className={tab}>
              {t("admin.tabs.audit")}
            </Tabs.Trigger>
          </Tabs.List>
          <Tabs.Content value="usage">
            <UsageTab />
          </Tabs.Content>
          <Tabs.Content value="users">
            <UsersTab />
          </Tabs.Content>
          <Tabs.Content value="audit">
            <AuditTab />
          </Tabs.Content>
        </Tabs.Root>
      </div>
    </main>
  );
}
