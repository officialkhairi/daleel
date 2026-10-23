import { useId, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

/** Small hand-rolled SVG charts for the usage dashboard (no chart library). Time runs left to
 * right in both languages; text uses ink tokens, never the series colour. */

export interface Series {
  key: string;
  label: string;
  color: string; // a CSS colour token, e.g. var(--color-series-1)
  values: (number | null)[];
}

interface ChartProps {
  title: string;
  labels: string[]; // one per x position (formatted dates)
  series: Series[];
  format: (value: number) => string;
  kind: "bars" | "lines";
}

const W = 640;
const H = 200;
const PAD = { top: 12, right: 12, bottom: 28, left: 52 };

function niceMax(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 2.5, 5, 10].find((s) => s * magnitude >= value / 4) ?? 10;
  return Math.ceil(value / (step * magnitude)) * step * magnitude;
}

function Legend({ series }: { series: Series[] }) {
  if (series.length < 2) return null; // one series: the title names it
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block size-2.5 rounded-sm" style={{ background: s.color }} />
          {s.label}
        </li>
      ))}
    </ul>
  );
}

function DataTable({ labels, series, format, caption }: Omit<ChartProps, "kind" | "title"> & { caption: string }) {
  const { t } = useTranslation();
  return (
    <table className="w-full text-start text-sm">
      <caption className="sr-only">{caption}</caption>
      <thead className="text-muted">
        <tr>
          <th scope="col" className="py-1 pe-3 text-start font-medium">
            {t("admin.day")}
          </th>
          {series.map((s) => (
            <th key={s.key} scope="col" className="py-1 pe-3 text-start font-medium">
              {s.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {labels.map((label, i) => (
          <tr key={label} className="border-t border-line">
            <th scope="row" className="py-1 pe-3 text-start font-normal text-muted">
              {label}
            </th>
            {series.map((s) => {
              const value = s.values[i];
              return (
                <td key={s.key} className="py-1 pe-3 tabular-nums text-ink">
                  {value === null || value === undefined ? "–" : format(value)}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function Chart({ title, labels, series, format, kind }: ChartProps) {
  const { t } = useTranslation();
  const id = useId();
  const [asTable, setAsTable] = useState(false);
  const [hover, setHover] = useState<number | null>(null);

  const n = labels.length;
  const totals = labels.map((_, i) =>
    kind === "bars"
      ? series.reduce((sum, s) => sum + (s.values[i] ?? 0), 0)
      : Math.max(0, ...series.map((s) => s.values[i] ?? 0)),
  );
  const max = niceMax(Math.max(0, ...totals));
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const band = plotW / Math.max(n, 1);
  const x = (i: number) => PAD.left + band * i + band / 2;
  const y = (v: number) => PAD.top + plotH - (v / max) * plotH;
  const ticks = [0, max / 2, max];
  const labelEvery = Math.ceil(n / 8);

  let marks: ReactNode;
  if (kind === "bars") {
    const barW = Math.max(2, Math.min(24, band * 0.6));
    marks = labels.map((label, i) => {
      let base = 0;
      return (
        <g key={label}>
          {series.map((s, si) => {
            const v = s.values[i] ?? 0;
            if (v <= 0) return null;
            const top = y(base + v);
            const bottom = y(base);
            base += v;
            const isTop = series.slice(si + 1).every((later) => (later.values[i] ?? 0) <= 0);
            // 2px surface gap between stacked segments; rounded ends only on the top segment.
            return (
              <rect
                key={s.key}
                x={x(i) - barW / 2}
                y={top}
                width={barW}
                height={Math.max(0, bottom - top - (si > 0 ? 2 : 0))}
                rx={isTop ? 3 : 0}
                fill={s.color}
              />
            );
          })}
        </g>
      );
    });
  } else {
    marks = series.map((s) => {
      const points = s.values.map((v, i) => (v === null ? null : `${String(x(i))},${String(y(v))}`));
      const segments: string[][] = [[]];
      for (const p of points) {
        if (p === null) segments.push([]);
        else segments.at(-1)?.push(p);
      }
      const lastIndex = s.values.findLastIndex((v) => v !== null);
      const last = lastIndex >= 0 ? s.values[lastIndex] : null;
      return (
        <g key={s.key}>
          {segments
            .filter((seg) => seg.length > 0)
            .map((seg) =>
              seg.length === 1 ? (
                <circle key={seg[0]} cx={seg[0]?.split(",")[0]} cy={seg[0]?.split(",")[1]} r={4} fill={s.color} />
              ) : (
                <polyline key={seg.join(" ")} points={seg.join(" ")} fill="none" stroke={s.color} strokeWidth={2} />
              ),
            )}
          {last !== null && last !== undefined && (
            <text x={x(lastIndex) + 6} y={y(last) - 6} fontSize={11} fill="var(--color-muted)">
              {s.label}
            </text>
          )}
        </g>
      );
    });
  }

  return (
    <figure className="bg-surface p-4" aria-labelledby={`${id}-title`}>
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <figcaption id={`${id}-title`} className="font-medium text-ink">
          {title}
        </figcaption>
        <Legend series={series} />
        <button
          type="button"
          aria-pressed={asTable}
          onClick={() => {
            setAsTable((v) => !v);
          }}
          className="ms-auto rounded px-2 py-1 text-xs text-muted hover:bg-brand-soft"
        >
          {asTable ? t("admin.showChart") : t("admin.showTable")}
        </button>
      </div>
      {asTable ? (
        <DataTable labels={labels} series={series} format={format} caption={title} />
      ) : (
        <div dir="ltr" className="relative">
          <svg viewBox={`0 0 ${String(W)} ${String(H)}`} className="w-full" role="img" aria-label={title}>
            {ticks.map((tick) => (
              <g key={tick}>
                <line x1={PAD.left} x2={W - PAD.right} y1={y(tick)} y2={y(tick)} stroke="var(--color-chart-grid)" />
                <text x={PAD.left - 6} y={y(tick) + 4} textAnchor="end" fontSize={11} fill="var(--color-muted)">
                  {format(tick)}
                </text>
              </g>
            ))}
            {labels.map((label, i) =>
              i % labelEvery === 0 ? (
                <text key={label} x={x(i)} y={H - 8} textAnchor="middle" fontSize={11} fill="var(--color-muted)">
                  {label}
                </text>
              ) : null,
            )}
            {hover !== null && kind === "lines" && (
              <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + plotH} stroke="var(--color-muted)" strokeDasharray="3 3" />
            )}
            {marks}
            {/* Hit targets: one full-height column per day, wider than any mark. */}
            {labels.map((label, i) => (
              <rect
                key={label}
                x={PAD.left + band * i}
                y={PAD.top}
                width={band}
                height={plotH}
                fill="transparent"
                onMouseEnter={() => {
                  setHover(i);
                }}
                onMouseLeave={() => {
                  setHover(null);
                }}
              />
            ))}
          </svg>
          {hover !== null && (
            <div
              role="tooltip"
              className="pointer-events-none absolute top-0 z-10 rounded-md border border-line bg-surface px-3 py-2 text-xs shadow"
              style={{ left: `min(calc(${String((x(hover) / W) * 100)}% + 8px), calc(100% - 10rem))` }}
            >
              <p className="font-medium text-ink">{labels[hover]}</p>
              {series.map((s) => {
                const v = s.values[hover];
                return (
                  <p key={s.key} className="flex items-center gap-1.5 text-muted">
                    <span aria-hidden className="inline-block size-2 rounded-sm" style={{ background: s.color }} />
                    {s.label}: <span className="tabular-nums text-ink">{v === null || v === undefined ? "–" : format(v)}</span>
                  </p>
                );
              })}
            </div>
          )}
        </div>
      )}
    </figure>
  );
}
