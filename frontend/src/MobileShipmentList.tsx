import { tabKeys } from "./tabKeys";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { clearedShipmentCount, listShipments } from "./api";
import { useAuth } from "./AuthContext";
import { formatPort, usePorts } from "./ports";
import { SHIPMENT_STATUS_LABELS, type Shipment } from "./types";
import { fmtDayShort } from "./dates";

const fmt = (v: string | null) => fmtDayShort(v);

/**
 * Shipments on a phone: search + one card per shipment (the tracker grid needs a desk).
 * Every card shows Job, client, BL and BE; admins get a straight "Proforma" button once the BE is filed (client, 2026-09-30).
 */
export default function MobileShipmentList() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "cleared" ? "cleared" : "ongoing";
  const [rows, setRows] = useState<Shipment[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [q, setQ] = useState("");
  const ports = usePorts();
  const isAdmin = useAuth().user?.role === "admin";

  const [clearedCount, setClearedCount] = useState<number | null>(null);
  // only the open tab loads; Cleared (the long history) waits until it's tapped
  useEffect(() => {
    let live = true;
    setRows(null);
    listShipments({ include_archived: true, cleared: tab === "cleared" })
      .then((r) => live && setRows(r))
      .catch(() => live && setFailed(true));
    if (tab === "ongoing") clearedShipmentCount().then((n) => live && setClearedCount(n), () => {});
    return () => {
      live = false;
    };
  }, [tab]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (rows ?? [])
      .filter((s) => (tab === "cleared" ? s.is_fully_cleared : !s.is_fully_cleared))
      .filter(
        (s) =>
          !needle ||
          [s.job, s.mbl, s.hbl, s.be_no, s.client, s.consignee].some((v) => (v ?? "").toLowerCase().includes(needle)),
      );
  }, [rows, tab, q]);
  const [ongoingCount, setOngoingCount] = useState<number | null>(null);
  useEffect(() => {
    if (!rows) return;
    if (tab === "ongoing") setOngoingCount(rows.filter((s) => !s.is_fully_cleared).length);
    else setClearedCount(rows.filter((s) => s.is_fully_cleared).length);
  }, [rows, tab]);
  const count = (t: "ongoing" | "cleared") => (t === "ongoing" ? ongoingCount : clearedCount) ?? "";

  return (
    <div className="m-page">
      <h1 className="m-title">Shipments</h1>
      <input
        className="m-search"
        type="search"
        inputMode="search"
        enterKeyHint="search"
        aria-label="Search shipments"
        placeholder="Job, BL, BE, client…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <div className="m-seg" role="tablist" onKeyDown={tabKeys} aria-label="Shipments">
        {(["ongoing", "cleared"] as const).map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            className={tab === t ? "on" : ""}
            onClick={() => setParams(t === "ongoing" ? {} : { tab: t })}
          >
            {t === "ongoing" ? "Ongoing" : "Cleared"} <span className="chip-count">{count(t)}</span>
          </button>
        ))}
      </div>

      {failed ? (
        <p className="field-note">Couldn’t load shipments. Pull down or reopen the page to try again.</p>
      ) : rows === null ? (
        <p className="field-note">Loading shipments…</p>
      ) : shown.length === 0 ? (
        <p className="field-note">{q ? `Nothing matches “${q}”.` : "No shipments here."}</p>
      ) : (
        <ul className="m-cards">
          {shown.map((s) => (
            <li key={s.id} className="m-card">
              <Link to={`/shipments/${s.id}`} className="m-card-main">
                <span className="m-card-top">
                  <strong>{s.job ? `Job ${s.job}` : "No job no."}</strong>
                  <span className={`status-pill status-${s.status}`}>{SHIPMENT_STATUS_LABELS[s.status]}</span>
                </span>
                <span className="m-card-client">{s.client || "—"} · {s.consignee || "—"}</span>
                <span className="m-card-ids">
                  <span>BL {s.mbl || "—"}</span>
                  <span>BE {s.be_no || "not filed"}</span>
                </span>
                <span className="m-card-meta">
                  ETA {fmt(s.eta)} · {formatPort(s.port, ports) || s.port || "—"}
                  {s.days !== "Pending" && ` · ${s.days}`}
                </span>
              </Link>
              {isAdmin && s.be_no && (
                <Link to={`/shipments/${s.id}?tab=proforma`} className="m-card-action">
                  Proforma
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
