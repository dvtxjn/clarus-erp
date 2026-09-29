import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getDashboardSummary } from "./api";
import DailyUpdates from "./DailyUpdates";
import { useAuth } from "./AuthContext";
import { formatPort, usePorts } from "./ports";
import { SHIPMENT_STATUS_LABELS, type DashboardSummary, type ShipmentStatus } from "./types";

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

  useEffect(() => {
    getDashboardSummary()
      .then(setSummary)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="tracker-empty">Loading…</div>;
  if (!summary) return <div className="tracker-empty">Couldn't load the dashboard.</div>;

  const pipelineTotal = PIPELINE_ORDER.reduce((n, st) => n + (summary.by_status[st] ?? 0), 0) || 1;
  const portMax = Math.max(1, ...Object.values(summary.by_port));
  const today = new Date(new Date().toDateString()).getTime();
  const inDays = (eta: string | null) => {
    if (!eta) return "";
    const d = Math.round((new Date(eta).getTime() - today) / 86_400_000);
    return d === 0 ? "today" : d === 1 ? "tomorrow" : d > 0 ? `in ${d} days` : `${-d} days ago`;
  };

  return (
    <div className="dashboard-page">
      <div className="dash-head">
        <h1>Dashboard</h1>
        <span className="tracker-subtitle">
          {new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}
        </span>
      </div>

      <div className="dash-layout">
        <div className="dash-main">
          <div className="stat-row">
            <Link to="/shipments?tab=ongoing" className="stat-card stat-card-link">
              <div className="stat-value">{summary.total_live}</div>
              <div className="stat-label">Ongoing shipments</div>
            </Link>
            <Link to="/shipments?tab=cleared" className="stat-card stat-card-link">
              <div className="stat-value">{summary.cleared_this_month}</div>
              <div className="stat-label">Cleared this month</div>
              {summary.cleared_this_month_unbilled > 0 && (
                <div className="stat-note">{summary.cleared_this_month_unbilled} not billed yet</div>
              )}
            </Link>
            <Link
              to="/shipments?tab=ongoing"
              className={`stat-card stat-card-link${summary.clearance_exceptions ? " stat-card-danger" : ""}`}
              title="Cleared Date entered but Duty / CFS Inv / Line / OOC / DO not all ticked"
            >
              <div className="stat-value">{summary.clearance_exceptions}</div>
              <div className="stat-label">Clearance exceptions</div>
            </Link>
            <div className="stat-card">
              <div className="stat-value">{Object.keys(summary.by_port).length}</div>
              <div className="stat-label">Ports active</div>
            </div>
          </div>

          <section className="dash-card">
            <div className="dash-card-head">Status pipeline</div>
            {/* one bar: each stage's share of the shipments */}
            <div className="pipeline-bar" aria-hidden>
              {PIPELINE_ORDER.map((st, i) => (
                <span
                  key={st}
                  style={{ flexGrow: summary.by_status[st] ?? 0, opacity: 0.35 + (0.65 * i) / (PIPELINE_ORDER.length - 1) }}
                  title={`${SHIPMENT_STATUS_LABELS[st]}: ${summary.by_status[st] ?? 0}`}
                />
              ))}
            </div>
            <div className="pipeline-row">
              {PIPELINE_ORDER.map((status) => (
                <Link to={`/shipments?status=${status}`} key={status} className="pipeline-card">
                  <div className="pipeline-count">{summary.by_status[status] ?? 0}</div>
                  <div className="pipeline-label">{SHIPMENT_STATUS_LABELS[status]}</div>
                  <div className="pipeline-share">{Math.round(((summary.by_status[status] ?? 0) * 100) / pipelineTotal)}%</div>
                </Link>
              ))}
            </div>
          </section>

          <section className="dash-card">
            <div className="dash-card-head">
              Upcoming shipments <span className="doc-group-count">{summary.upcoming_etas.length}</span>
            </div>
            {summary.upcoming_etas.length === 0 ? (
              <p className="tracker-subtitle">Nothing scheduled.</p>
            ) : (
              <table className="tracker-grid dash-table">
                <thead>
                  <tr>
                    <th>Job / MBL</th>
                    <th>Consignee</th>
                    <th>Port</th>
                    <th>ETA</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {summary.upcoming_etas.map((s) => (
                    <tr key={s.id}>
                      <td>
                        <Link to={`/shipments/${s.id}`}>{s.job ? `Job ${s.job}` : s.mbl}</Link>
                      </td>
                      <td>{s.consignee ?? "—"}</td>
                      <td>{formatPort(s.port, ports) || "—"}</td>
                      <td>{s.eta ?? "—"}</td>
                      <td className="dash-when">{inDays(s.eta)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>

        <aside className="dash-side">
          {isAdmin && <DailyUpdates /> /* challans + organisations feed invoicing: admin-only */}
          <section className="dash-card">
            <div className="dash-card-head">By port</div>
            <ul className="port-bars">
              {Object.entries(summary.by_port).map(([port, count]) => (
                <li key={port}>
                  <span className="port-name">{port === "Unassigned" ? port : formatPort(port, ports)}</span>
                  <span className="port-bar">
                    <span style={{ width: `${(count * 100) / portMax}%` }} />
                  </span>
                  <span className="simple-list-count">{count}</span>
                </li>
              ))}
            </ul>
          </section>
        </aside>
      </div>
    </div>
  );
}
