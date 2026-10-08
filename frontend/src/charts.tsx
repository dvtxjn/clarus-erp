import type { MonthFigures } from "./types";
import { MONTHS } from "./dates";

/**
 * Small SVG charts for the dashboard (no chart library): monthly stacked bars by port and
 * a donut of one month by port. "metric" switches containers / gross weight.
 */
export type Metric = "containers" | "tonnes";

const PORT_COLORS = ["var(--color-accent)", "#5E7FB8", "#4E9A7A", "#B58A3C", "#8A6BB0", "#9A9A94"];

export function portColors(ports: string[]): Record<string, string> {
  return Object.fromEntries(ports.map((p, i) => [p, PORT_COLORS[i % PORT_COLORS.length]]));
}

export const fmtMetric = (v: number, m: Metric) =>
  m === "containers" ? v.toLocaleString("en-IN") : `${v.toLocaleString("en-IN", { maximumFractionDigits: 1 })} t`;

const monthLabel = (ym: string) =>
  `${MONTHS[Number(ym.slice(5, 7)) - 1]} ${ym.slice(2, 4)}`;

export function MonthlyBars({
  data,
  metric,
  colors,
  highlight,
  portLabel,
}: {
  data: MonthFigures[];
  metric: Metric;
  colors: Record<string, string>;
  highlight?: string;
  portLabel: (p: string) => string;
}) {
  if (data.length === 0) return <p className="tracker-subtitle">No data yet.</p>;
  const W = 640, H = 200, top = 18, bottom = 22, gap = 10;
  const max = Math.max(1, ...data.map((m) => m[metric]));
  const bw = Math.min(56, (W - gap * (data.length + 1)) / data.length);
  const x0 = (W - (bw * data.length + gap * (data.length - 1))) / 2;
  const scale = (v: number) => (v / max) * (H - top - bottom);
  const shown = [...new Set(data.flatMap((m) => Object.keys(m.by_port).filter((p) => m.by_port[p][metric] > 0)))].sort();
  return (
    <>
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label={`${metric} per month`}>
      <line x1={0} x2={W} y1={H - bottom} y2={H - bottom} className="chart-axis" />
      {data.map((m, i) => {
        const x = x0 + i * (bw + gap);
        let y = H - bottom;
        return (
          <g key={m.month}>
            {Object.entries(m.by_port).map(([port, v]) => {
              const h = scale(v[metric]);
              y -= h;
              return (
                <rect key={port} x={x} y={y} width={bw} height={Math.max(0, h)} fill={colors[port]} rx={1.5}>
                  <title>{`${monthLabel(m.month)} · ${portLabel(port)}: ${fmtMetric(v[metric], metric)}`}</title>
                </rect>
              );
            })}
            <text x={x + bw / 2} y={H - bottom - scale(m[metric]) - 5} className="chart-value" textAnchor="middle">
              {fmtMetric(Math.round(m[metric]), metric)}
            </text>
            <text
              x={x + bw / 2}
              y={H - 6}
              className={`chart-label${m.month === highlight ? " chart-label-on" : ""}`}
              textAnchor="middle"
            >
              {monthLabel(m.month)}
            </text>
          </g>
        );
      })}
    </svg>
    <ul className="chart-legend" aria-label="Ports">
      {shown.map((p) => (
        <li key={p}>
          <span className="legend-dot" style={{ background: colors[p] }} />
          {portLabel(p)}
        </li>
      ))}
    </ul>
    </>
  );
}

export function PortDonut({
  month,
  metric,
  colors,
  portLabel,
  emptyText,
}: {
  month: MonthFigures | undefined;
  metric: Metric;
  colors: Record<string, string>;
  portLabel: (p: string) => string;
  emptyText?: string;
}) {
  const entries = Object.entries(month?.by_port ?? {}).filter(([, v]) => v[metric] > 0);
  const total = entries.reduce((n, [, v]) => n + v[metric], 0);
  const R = 52, C = 2 * Math.PI * R;
  let offset = 0;
  if (entries.length === 0) return <p className="tracker-subtitle chart-empty">{emptyText ?? "Nothing this month."}</p>;
  return (
    <div className="donut">
      <svg viewBox="0 0 140 140" className="donut-svg" role="img" aria-label="Share by port">
        <circle cx={70} cy={70} r={R} className="donut-track" />
        {entries.map(([port, v]) => {
          const len = (v[metric] / (total || 1)) * C;
          const el = (
            <circle
              key={port}
              cx={70}
              cy={70}
              r={R}
              fill="none"
              stroke={colors[port]}
              strokeWidth={18}
              strokeDasharray={`${len} ${C - len}`}
              strokeDashoffset={-offset}
              transform="rotate(-90 70 70)"
            >
              <title>{`${portLabel(port)}: ${fmtMetric(v[metric], metric)}`}</title>
            </circle>
          );
          offset += len;
          return el;
        })}
        <text x={70} y={68} textAnchor="middle" className="donut-total">
          {fmtMetric(Math.round(total), metric)}
        </text>
        <text x={70} y={84} textAnchor="middle" className="donut-caption">
          {metric === "containers" ? "containers" : "gross wt"}
        </text>
      </svg>
      <ul className="donut-legend">
        {entries.map(([port, v]) => (
          <li key={port}>
            <span className="legend-dot" style={{ background: colors[port] }} />
            <span className="port-name">{portLabel(port)}</span>
            <span className="legend-val">{fmtMetric(v[metric], metric)}</span>
            <span className="legend-pct">{Math.round((v[metric] * 100) / (total || 1))}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
