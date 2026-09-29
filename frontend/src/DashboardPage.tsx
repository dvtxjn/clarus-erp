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

  return (
    <div className="dashboard-page">
      <h1>Tracker Dashboard</h1>

      {isAdmin && <DailyUpdates /> /* challans + organisations feed invoicing: admin-only */}

      <div className="stat-row">
        <div className="stat-card">
          <div className="stat-value">{summary.total_live}</div>
          <div className="stat-label">Ongoing shipments</div>
        </div>
        <Link to="/shipments?tab=cleared" className="stat-card stat-card-link">
          <div className="stat-value">{summary.cleared_this_month}</div>
          <div className="stat-label">
            Cleared this month · {summary.cleared_this_month_unbilled} not billed
          </div>
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

      <h2>Status Pipeline</h2>
      <div className="pipeline-row">
        {PIPELINE_ORDER.map((status) => (
          <Link to={`/shipments?status=${status}`} key={status} className="pipeline-card">
            <div className="pipeline-count">{summary.by_status[status] ?? 0}</div>
            <div className="pipeline-label">{SHIPMENT_STATUS_LABELS[status]}</div>
          </Link>
        ))}
      </div>

      <div className="dashboard-columns">
        <section>
          <h2>By Port</h2>
          <ul className="simple-list">
            {Object.entries(summary.by_port).map(([port, count]) => (
              <li key={port}>
                <span>{port === "Unassigned" ? port : formatPort(port, ports)}</span>
                <span className="simple-list-count">{count}</span>
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h2>Upcoming Shipments</h2>
          {summary.upcoming_etas.length === 0 ? (
            <p className="tracker-subtitle">Nothing scheduled.</p>
          ) : (
            <ul className="simple-list">
              {summary.upcoming_etas.map((s) => (
                <li key={s.id}>
                  <span>
                    <Link to={`/shipments/${s.id}`}>{s.job ? `Job ${s.job}` : s.mbl}</Link>
                    <span className="tracker-subtitle"> · {s.consignee ?? "—"} · {formatPort(s.port, ports)}</span>
                  </span>
                  <span className="simple-list-count">{s.eta}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
