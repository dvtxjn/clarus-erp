import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getAlerts, refreshIcegate, type AlertKind, type ShipmentAlert } from "./api";

const KINDS: { id: AlertKind; label: string }[] = [
  { id: "deadline", label: "Deadlines" },
  { id: "free_days", label: "Free days" },
  { id: "documents", label: "Not attached" },
  { id: "icegate", label: "ICEGATE" },
];
const SEVERITY = { overdue: "Overdue", urgent: "Urgent", soon: "Soon" } as const;
const SHOWN = 6;

/**
 * Dashboard "Needs attention" (client, 2026-09-30): "d" deadlines (move to CFS 4 days before ETA),
 * 14 free days at the POD from the inward date, and basic documents missing before the BE is filed.
 */
export default function NeedsAttention() {
  const [alerts, setAlerts] = useState<ShipmentAlert[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [kind, setKind] = useState<AlertKind | null>(null);
  const [all, setAll] = useState(false);

  useEffect(() => {
    getAlerts()
      .then(setAlerts)
      .catch(() => setFailed(true));
  }, []);

  const [looking, setLooking] = useState<number | null>(null);
  const [looked, setLooked] = useState<Record<number, string>>({});

  // the fix sits on the flagged row itself (client: buttons next to the task)
  async function lookUp(id: number) {
    setLooking(id);
    try {
      const { summary } = await refreshIcegate(id);
      const found = summary.sea_found || summary.icd_found;
      setLooked((m) => ({ ...m, [id]: found ? "Found on ICEGATE — updated." : "Still not found. Check the BL no. on the shipment." }));
      setAlerts(await getAlerts());
    } catch {
      setLooked((m) => ({ ...m, [id]: "ICEGATE didn't answer — try again in a minute." }));
    } finally {
      setLooking(null);
    }
  }

  const count = (k: AlertKind) => alerts?.filter((a) => a.kind === k).length ?? 0;
  // one row per job, all its reasons together (QA 2026-10-07: Job 191 was listed twice); alerts come worst first
  const list: ShipmentAlert[][] = [];
  const at = new Map<number, ShipmentAlert[]>();
  for (const a of (alerts ?? []).filter((a) => !kind || a.kind === kind)) {
    const g = at.get(a.shipment_id);
    if (g) g.push(a);
    else {
      const n = [a];
      at.set(a.shipment_id, n);
      list.push(n);
    }
  }
  const shown = all ? list : list.slice(0, SHOWN);

  return (
    <section className="dash-card attention" aria-labelledby="attention-head">
      <div className="dash-card-head-row">
        <h2 id="attention-head" className="dash-card-head">
          Needs attention{alerts && alerts.length > 0 && <span className="attention-total" title="jobs">{new Set(alerts.map((a) => a.shipment_id)).size}</span>}
        </h2>
        {alerts && alerts.length > 0 && (
          <div className="seg-switch" role="group" aria-label="Show">
            <button type="button" className={kind === null ? "on" : ""} aria-pressed={kind === null} onClick={() => setKind(null)}>
              All
            </button>
            {KINDS.map((k) => (
              <button
                key={k.id}
                type="button"
                className={kind === k.id ? "on" : ""}
                aria-pressed={kind === k.id}
                disabled={count(k.id) === 0}
                onClick={() => setKind(k.id)}
              >
                {k.label} <span className="chip-count">{count(k.id)}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {failed ? (
        <p className="field-note">Couldn’t load alerts. Refresh the page to try again.</p>
      ) : alerts === null ? (
        <p className="field-note">Checking deadlines, free days and documents…</p>
      ) : alerts.length === 0 ? (
        <p className="attention-empty">
          All clear: no “d” deadlines, free-day limits, missing documents, ICEGATE queries or IGMs missing near the ETA.
        </p>
      ) : (
        <>
          <ul className="attention-list">
            {shown.map((g) => {
              const a = g[0];
              const lookup = g.find((x) => x.lookup);
              return (
              <li key={a.shipment_id} className={`attention-row sev-${a.severity}`}>
                <span className="attention-sev">{SEVERITY[a.severity]}</span>
                <span className="attention-who">
                  <span className="attention-line">
                    <Link className="attention-job" to={`/shipments/${a.shipment_id}${a.kind === "documents" ? "?tab=documents" : a.kind === "icegate" ? "?tab=customs" : ""}`} translate="no">
                      {a.job ? `Job ${a.job}` : `BL ${a.mbl || "—"}`}
                    </Link>
                    {!a.job && <span className="field-note">no job no.</span>}
                    <span className="attention-client">{a.client || a.consignee || "—"}</span>
                  </span>
                  <span className="attention-ids">
                    BL {a.mbl || "—"} · BE {a.be_no || "not filed"}
                  </span>
                </span>
                <span className="attention-text">
                  {g.map((x, i) => (
                    <span key={`${x.kind}-${x.mail_id ?? i}`} className="attention-reason">
                      {x.text}
                    </span>
                  ))}
                  {lookup && a.mbl && (
                    <span className="attention-action">
                      <button type="button" className="btn-secondary btn-small" disabled={looking !== null} onClick={() => lookUp(a.shipment_id)}>
                        {looking === a.shipment_id ? "Looking up…" : "Look up again"}
                      </button>
                      {looked[a.shipment_id] && (
                        <span role="status" aria-live="polite" className="field-note">
                          {looked[a.shipment_id]}
                        </span>
                      )}
                    </span>
                  )}
                </span>
              </li>
              );
            })}
          </ul>
          {list.length > SHOWN && (
            <button type="button" className="link-button attention-more" onClick={() => setAll((x) => !x)}>
              {all ? "Show fewer" : `Show all ${list.length}`}
            </button>
          )}
        </>
      )}
    </section>
  );
}
