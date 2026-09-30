import { useEffect, useState, type FormEvent } from "react";
import axios from "axios";
import {
  addContainer,
  editContainer,
  listContainers,
  refreshContainersFromIcegate,
  removeContainer,
  type IcdRefresh,
  type ShipmentContainer,
} from "./api";
import { useConfirm } from "./ConfirmDialog";

// free days at the FPOD, counted from each container's arrival (arrival = day 1)
const FREE_DAYS = 14;
const fmt = (v: string | null) =>
  v ? new Date(`${v}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "—";
const errText = (e: unknown) =>
  axios.isAxiosError(e) && typeof e.response?.data?.detail === "string" ? e.response.data.detail : "Something went wrong — try again.";

/**
 * Inland shipments (client, 2026-09-30): every container and its arrival at the FPOD (ICD), where the
 * free days start — per container. Fetched from ICEGATE's ICD BL status (MBL only) on command, or typed;
 * a date typed by hand is kept when ICEGATE is fetched again.
 */
export default function FpodContainers({ shipmentId, portLabel }: { shipmentId: number; portLabel: string }) {
  const [rows, setRows] = useState<ShipmentContainer[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [bl, setBl] = useState<IcdRefresh["bl"]>(null);
  const [adding, setAdding] = useState(false);
  const [newNo, setNewNo] = useState("");
  const [newDate, setNewDate] = useState("");
  const confirm = useConfirm();

  useEffect(() => {
    listContainers(shipmentId).then(setRows).catch(() => setRows([]));
  }, [shipmentId]);

  async function fetchIcegate() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await refreshContainersFromIcegate(shipmentId);
      setRows(r.containers);
      setBl(r.bl);
      setMsg(
        r.found
          ? {
              ok: true,
              text: `ICEGATE: ${r.added} added, ${r.updated} arrival${r.updated === 1 ? "" : "s"} updated${r.kept_manual ? `, ${r.kept_manual} typed by hand kept` : ""}.`,
            }
          : { ok: false, text: "ICEGATE has nothing for this MBL at an ICD yet." },
      );
    } catch (e) {
      setMsg({ ok: false, text: errText(e) });
    } finally {
      setBusy(false);
    }
  }

  async function saveDate(c: ShipmentContainer, value: string) {
    if ((c.arrival_date ?? "") === value) return;
    try {
      const saved = await editContainer(shipmentId, c.id, value ? { arrival_date: value } : { clear_arrival: true });
      setRows((prev) => prev?.map((x) => (x.id === c.id ? saved : x)) ?? prev);
      setMsg({ ok: true, text: `Saved arrival for ${c.container_no}` });
    } catch (e) {
      setMsg({ ok: false, text: errText(e) });
    }
  }

  async function add(e: FormEvent) {
    e.preventDefault();
    try {
      const saved = await addContainer(shipmentId, { container_no: newNo, arrival_date: newDate || null });
      setRows((prev) => [...(prev ?? []), saved].sort((a, b) => a.container_no.localeCompare(b.container_no)));
      setNewNo("");
      setNewDate("");
      setAdding(false);
    } catch (err) {
      setMsg({ ok: false, text: errText(err) });
    }
  }

  async function remove(c: ShipmentContainer) {
    if (!(await confirm({ title: `Remove ${c.container_no}?`, message: "It comes off this shipment (an admin can restore it).", confirmLabel: "Remove", danger: true })))
      return;
    try {
      await removeContainer(shipmentId, c.id);
      setRows((prev) => prev?.filter((x) => x.id !== c.id) ?? prev);
    } catch (e) {
      setMsg({ ok: false, text: errText(e) });
    }
  }

  const tone = (c: ShipmentContainer) =>
    c.day == null ? "" : c.day > FREE_DAYS ? " fpod-over" : c.day > FREE_DAYS - 3 ? " fpod-soon" : "";
  const arrived = (rows ?? []).filter((c) => c.arrival_date).length;

  return (
    <section className="detail-section detail-wide fpod">
      <div className="fpod-head">
        <h3>Containers at FPOD · {portLabel}</h3>
        <span className="field-note">
          {rows ? `${rows.length} container${rows.length === 1 ? "" : "s"} · ${arrived} arrived` : ""} · {FREE_DAYS} free days from each
          container’s arrival
        </span>
        <span className="fpod-actions">
          <button type="button" className="btn-secondary" onClick={fetchIcegate} disabled={busy}>
            {busy ? "Asking ICEGATE…" : "Fetch from ICEGATE"}
          </button>
          <button type="button" className="btn-secondary" onClick={() => setAdding((a) => !a)}>
            + Add container
          </button>
        </span>
      </div>
      {msg && (
        <div role="status" className={msg.ok ? "grid-toast grid-toast-ok" : "grid-toast grid-toast-error"}>
          {msg.text}
        </div>
      )}
      {bl && (
        <p className="field-note">
          Gateway {bl.gateway_port ?? "—"} · IGM {bl.igm_no ?? "—"} ({fmt(bl.igm_date)}) · inward {fmt(bl.inward_date)} · SMTP{" "}
          {bl.smtp_no ?? "—"} ({fmt(bl.smtp_date)})
        </p>
      )}
      {adding && (
        <form className="fpod-add" onSubmit={add}>
          <input aria-label="Container number" placeholder="Container no, e.g. MRKU5032093…" value={newNo} onChange={(e) => setNewNo(e.target.value)} required autoComplete="off" spellCheck={false} />
          <input aria-label="Arrival at FPOD" type="date" value={newDate} onChange={(e) => setNewDate(e.target.value)} />
          <button type="submit">Add</button>
        </form>
      )}
      {rows === null ? (
        <p className="field-note">Loading containers…</p>
      ) : rows.length === 0 ? (
        <p className="field-note">No containers yet: Fetch from ICEGATE (needs only the MBL), or add them by hand.</p>
      ) : (
        <table className="tracker-grid fpod-table">
          <thead>
            <tr>
              <th>Container</th>
              <th>Type</th>
              <th>Arrived at FPOD</th>
              <th>Day</th>
              <th>Free until</th>
              <th>Source</th>
              <th aria-label="Remove" />
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id}>
                <td className="fpod-no">{c.container_no}</td>
                <td>{c.status ?? "—"}</td>
                <td>
                  <input
                    type="date"
                    className="fpod-date"
                    aria-label={`Arrival of ${c.container_no}`}
                    defaultValue={c.arrival_date ?? ""}
                    key={c.arrival_date ?? "none"}
                    onBlur={(e) => saveDate(c, e.target.value)}
                  />
                </td>
                <td className={`num${tone(c)}`}>
                  {c.day == null ? "—" : c.day > FREE_DAYS ? `Day ${c.day} · ${c.day - FREE_DAYS} over` : `Day ${c.day}`}
                </td>
                <td>{fmt(c.last_free_day)}</td>
                <td>
                  <span className={`fpod-src${c.is_manual ? " is-manual" : ""}`}>{c.is_manual ? "Typed" : c.source === "icegate" ? "ICEGATE" : "Typed"}</span>
                </td>
                <td>
                  <button type="button" className="link-button link-danger" aria-label={`Remove ${c.container_no}`} onClick={() => remove(c)}>
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
