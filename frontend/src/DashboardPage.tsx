import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getDashboardSummary } from "./api";
import DailyUpdates from "./DailyUpdates";
import NeedsAttention from "./NeedsAttention";
import { useAuth } from "./AuthContext";
import { formatPort, usePorts } from "./ports";
import { SHIPMENT_STATUS_LABELS, type DashboardSummary, type ShipmentStatus } from "./types";
import { MonthlyBars, PortDonut, fmtMetric, portColors, type Metric } from "./charts";

const PIPELINE_ORDER: ShipmentStatus[] = [
  "to_be_filed",
  "igm_filed",
  "be_filed",
  "be_assessed",
  "duty_paid",
  "under_ooc",
  "ooc_done",
  "cleared",
  "billed",
];

export default function DashboardPage() {
  const ports = usePorts();
  const isAdmin = useAuth().user?.role === "admin";
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [metric, setMetricState] = useState<Metric>(() => {
    try {
      return localStorage.getItem("clarus.dashMetric") === "tonnes" ? "tonnes" : "containers";
    } catch {
      return "containers";
    }
  });
  const setMetric = (m: Metric) => {
    setMetricState(m);
    try {
      localStorage.setItem("clarus.dashMetric", m);
    } catch {
      /* private window */
    }
  };
  const [clearedMonth, setClearedMonth] = useState<string | null>(null);

  useEffect(() => {
    getDashboardSummary()
      .then(setSummary)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="tracker-empty">Loading…</div>;
  if (!summary) return <div className="tracker-empty">Couldn't load the dashboard.</div>;

  const pipelineTotal = PIPELINE_ORDER.reduce((n, st) => n + (summary.by_status[st] ?? 0), 0) || 1;
  const today = new Date(new Date().toDateString()).getTime();
  const inDays = (eta: string | null) => {
    if (!eta) return "";
    const d = Math.round((new Date(eta).getTime() - today) / 86_400_000);
    return d === 0 ? "today" : d === 1 ? "tomorrow" : d > 0 ? `in ${d} days` : `${-d} days ago`;
  };
  const portLabel = (p: string) => (p === "Unassigned" ? p : formatPort(p, ports) || p);
  const allPorts = [
    ...new Set(
      [...summary.containers_by_eta_month, ...summary.containers_cleared_by_month].flatMap((m) => Object.keys(m.by_port)),
    ),
  ].sort();
  const colors = portColors(allPorts);
  const monthName = (ym: string) => new Date(`${ym}-01T00:00:00`).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
  const find = (list: typeof summary.containers_by_eta_month, ym: string) => list.find((m) => m.month === ym);
  const arriving = find(summary.containers_by_eta_month, summary.this_month);
  const clearedPick = clearedMonth ?? summary.last_month;
  const cleared = find(summary.containers_cleared_by_month, clearedPick);
  const lastCleared = find(summary.containers_cleared_by_month, summary.last_month);
  const both = (m: { containers: number; tonnes: number } | undefined) =>
    `${fmtMetric(m?.containers ?? 0, "containers")} cntr · ${fmtMetric(m?.tonnes ?? 0, "tonnes")}`;
  const clearedMonths = [...new Set([summary.last_month, ...summary.containers_cleared_by_month.map((m) => m.month)])].sort().reverse();

  return (
    <div className="dashboard-page">
      <div className="dash-head">
        <h1>Dashboard</h1>
        <span className="tracker-subtitle">
          {new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}
        </span>
        {/* containers and weight are what matter (client, 2026-09-29) — not the number of shipments */}
        <div className="seg-switch">
          <button type="button" className={metric === "containers" ? "on" : ""} onClick={() => setMetric("containers")}>
            Containers
          </button>
          <button type="button" className={metric === "tonnes" ? "on" : ""} onClick={() => setMetric("tonnes")}>
            Gross weight
          </button>
        </div>
      </div>

      <div className="dash-layout">
        <div className="dash-main">
          <div className="stat-row">
            <Link to="/shipments?tab=ongoing" className="stat-card stat-card-link">
              <div className="stat-value">{fmtMetric(metric === "containers" ? summary.live_containers : summary.live_tonnes, metric)}</div>
              <div className="stat-label">In progress (not cleared)</div>
              <div className="stat-sub">{both({ containers: summary.live_containers, tonnes: summary.live_tonnes })}</div>
            </Link>
            <div className="stat-card">
              <div className="stat-value">{fmtMetric(arriving?.[metric] ?? 0, metric)}</div>
              <div className="stat-label">Arriving in {monthName(summary.this_month)} (ETA)</div>
              <div className="stat-sub">{both(arriving)}</div>
            </div>
            <Link to="/shipments?tab=cleared" className="stat-card stat-card-link">
              <div className="stat-value">{fmtMetric(lastCleared?.[metric] ?? 0, metric)}</div>
              <div className="stat-label">Cleared in {monthName(summary.last_month)}</div>
              <div className="stat-sub">{both(lastCleared)}</div>
            </Link>
            <Link
              to="/shipments?tab=ongoing"
              className={`stat-card stat-card-link${summary.clearance_exceptions ? " stat-card-danger" : ""}`}
              title="Cleared Date entered but Duty / CFS Inv / Line / OOC / DO not all ticked"
            >
              <div className="stat-value">{summary.clearance_exceptions}</div>
              <div className="stat-label">Clearance exceptions</div>
              {summary.cleared_this_month_unbilled > 0 && (
                <div className="stat-note">{summary.cleared_this_month_unbilled} cleared this month not billed</div>
              )}
            </Link>
          </div>

          <NeedsAttention />

          <div className="dash-pair">
            <section className="dash-card">
              <div className="dash-card-head">
                {metric === "containers" ? "Containers" : "Gross weight"} by ETA, month on month
              </div>
              <MonthlyBars data={summary.containers_by_eta_month} metric={metric} colors={colors} highlight={summary.this_month} portLabel={portLabel} />
            </section>
            <section className="dash-card">
              <div className="dash-card-head">
                {metric === "containers" ? "Containers" : "Gross weight"} cleared, month on month
              </div>
              <MonthlyBars data={summary.containers_cleared_by_month} metric={metric} colors={colors} highlight={summary.last_month} portLabel={portLabel} />
            </section>
          </div>

          <div className="dash-pair">
            <section className="dash-card">
              <div className="dash-card-head dash-card-head-row">
                <span>Containers cleared by port</span>
                <select value={clearedPick} onChange={(e) => setClearedMonth(e.target.value)} aria-label="Month">
                  {clearedMonths.map((m) => (
                    <option key={m} value={m}>
                      {monthName(m)}
                    </option>
                  ))}
                </select>
              </div>
              {/* always containers (client, 2026-09-29) */}
              <PortDonut month={cleared} metric="containers" colors={colors} portLabel={portLabel} />
            </section>
            <section className="dash-card">
              <div className="dash-card-head">Arriving in {monthName(summary.this_month)} by port (ETA)</div>
              <PortDonut month={arriving} metric={metric} colors={colors} portLabel={portLabel} />
            </section>
          </div>
        </div>

        <aside className="dash-side">
          {isAdmin && <DailyUpdates /> /* challans + organisations feed invoicing: admin-only */}
          <section className="dash-card">
            <div className="dash-card-head">Upcoming shipments</div>
            {summary.upcoming_etas.length === 0 ? (
              <p className="tracker-subtitle">Nothing scheduled.</p>
            ) : (
              <ul className="upcoming-list">
                {summary.upcoming_etas.map((s) => (
                  <li key={s.id}>
                    <span className="upcoming-main">
                      <Link to={`/shipments/${s.id}`}>{s.job ? `Job ${s.job}` : "open"}</Link>{" "}
                      <span className="tracker-subtitle">
                        BL {s.mbl || "—"} · BE {s.be_no || "—"}
                      </span>
                      <span className="tracker-subtitle">
                        {s.consignee ?? "—"} · {portLabel(s.port ?? "Unassigned")}
                      </span>
                    </span>
                    <span className="dash-when">{inDays(s.eta)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="dash-card">
            <div className="dash-card-head">Status pipeline (shipments)</div>
            <div className="pipeline-bar" aria-hidden>
              {PIPELINE_ORDER.map((st, i) => (
                <span
                  key={st}
                  style={{ flexGrow: summary.by_status[st] ?? 0, opacity: 0.35 + (0.65 * i) / (PIPELINE_ORDER.length - 1) }}
                  title={`${SHIPMENT_STATUS_LABELS[st]}: ${summary.by_status[st] ?? 0}`}
                />
              ))}
            </div>
            <div className="pipeline-list">
              {PIPELINE_ORDER.map((status) => (
                <Link to={`/shipments?status=${status}`} key={status}>
                  <span>{SHIPMENT_STATUS_LABELS[status]}</span>
                  <span className="simple-list-count">
                    {summary.by_status[status] ?? 0} · {Math.round(((summary.by_status[status] ?? 0) * 100) / pipelineTotal)}%
                  </span>
                </Link>
              ))}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
