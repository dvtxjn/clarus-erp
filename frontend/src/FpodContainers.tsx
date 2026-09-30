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
import type { Shipment } from "./types";

const STANDARD_FREE_DAYS = 14;
const fmt = (v: string | null) =>
  v ? new Date(`${v}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "—";
const errText = (e: unknown) =>
  axios.isAxiosError(e) && typeof e.response?.data?.detail === "string" ? e.response.data.detail : "Something went wrong — try again.";
type Patch = Parameters<typeof editContainer>[2];

/**
 * Inland shipments (client, 2026-09-30): every container, its arrival at the FPOD (ICD) and its own free
 * days (standard 14, or typed — as days or as a "free until" date). Fetched from ICEGATE's ICD BL status
 * (MBL only) on command, or typed; a typed arrival survives a refresh. A typed Status covers containers
 * that haven't arrived ("On rail"). "Copy as image" puts the table on the clipboard for the client.
 */
export default function FpodContainers({ shipment, portLabel }: { shipment: Shipment; portLabel: string }) {
  const shipmentId = shipment.id;
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

  async function save(c: ShipmentContainer, patch: Patch, what: string) {
    try {
      const saved = await editContainer(shipmentId, c.id, patch);
      setRows((prev) => prev?.map((x) => (x.id === c.id ? saved : x)) ?? prev);
      setMsg({ ok: true, text: `Saved ${what} for ${c.container_no}` });
    } catch (e) {
      setMsg({ ok: false, text: errText(e) });
      setRows((prev) => (prev ? [...prev] : prev)); // redraw the inputs with the saved values
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

  async function copyImage() {
    if (!rows?.length) return;
    const blob = tableImage(shipment, portLabel, rows);
    try {
      // the promise goes straight into the ClipboardItem so Safari keeps the click's permission
      await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
      setMsg({ ok: true, text: "Copied as an image — paste it into WhatsApp or the mail." });
    } catch {
      const url = URL.createObjectURL(await blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `containers-job-${shipment.job ?? shipment.mbl}.png`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMsg({ ok: true, text: "This browser can't copy images — downloaded it instead." });
    }
  }

  const tone = (c: ShipmentContainer) => (c.days_left == null ? "" : c.days_left < 0 ? " fpod-over" : c.days_left <= 3 ? " fpod-soon" : "");
  const arrived = (rows ?? []).filter((c) => c.arrival_date).length;

  return (
    <section className="detail-section detail-wide fpod">
      <div className="fpod-head">
        <h3>Containers at FPOD · {portLabel}</h3>
        <span className="field-note">
          {rows ? `${rows.length} container${rows.length === 1 ? "" : "s"} · ${arrived} arrived · ` : ""}
          free days count from each container’s arrival (standard {STANDARD_FREE_DAYS})
        </span>
        <span className="fpod-actions">
          <button type="button" className="btn-secondary" onClick={copyImage} disabled={!rows?.length}>
            Copy as image
          </button>
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
              <th>Status</th>
              <th>Arrived at FPOD</th>
              <th className="num">Days free</th>
              <th>Free until</th>
              <th className="num">Day</th>
              <th>Source</th>
              <th aria-label="Remove" />
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={`${c.id}-${c.arrival_date}-${c.free_days}-${c.tracking_status}`}>
                <td className="fpod-no">{c.container_no}</td>
                <td>{c.status ?? "—"}</td>
                <td>
                  <input
                    className="fpod-cell fpod-status"
                    aria-label={`Status of ${c.container_no}`}
                    placeholder={c.arrival_date ? "Arrived" : "e.g. On rail…"}
                    defaultValue={c.tracking_status ?? ""}
                    onBlur={(e) => e.target.value.trim() !== (c.tracking_status ?? "") && save(c, { tracking_status: e.target.value }, "status")}
                  />
                </td>
                <td>
                  <input
                    type="date"
                    className="fpod-cell"
                    aria-label={`Arrival of ${c.container_no}`}
                    defaultValue={c.arrival_date ?? ""}
                    onBlur={(e) =>
                      e.target.value !== (c.arrival_date ?? "") &&
                      save(c, e.target.value ? { arrival_date: e.target.value } : { clear_arrival: true }, "arrival")
                    }
                  />
                </td>
                <td className="num">
                  <input
                    type="number"
                    inputMode="numeric"
                    min={0}
                    className={`fpod-cell fpod-days${c.free_days_typed ? " is-typed" : ""}`}
                    aria-label={`Days free for ${c.container_no}`}
                    title={c.free_days_typed ? "Typed for this container (clear it for the standard 14)" : "Standard free days"}
                    defaultValue={c.free_days_typed ? c.free_days : ""}
                    placeholder={String(c.free_days)}
                    onBlur={(e) => {
                      const v = e.target.value.trim();
                      if (v === (c.free_days_typed ? String(c.free_days) : "")) return;
                      save(c, v === "" ? { clear_free_days: true } : { free_days: Number(v) }, "days free");
                    }}
                  />
                </td>
                <td>
                  <input
                    type="date"
                    className="fpod-cell"
                    aria-label={`Free until for ${c.container_no}`}
                    disabled={!c.arrival_date}
                    title={c.arrival_date ? "" : "Enter the arrival first (or type the days free)"}
                    defaultValue={c.last_free_day ?? ""}
                    onBlur={(e) => e.target.value && e.target.value !== (c.last_free_day ?? "") && save(c, { free_until: e.target.value }, "free until")}
                  />
                </td>
                <td className={`num${tone(c)}`}>
                  {c.day == null ? "—" : c.days_left != null && c.days_left < 0 ? `Day ${c.day} · ${-c.days_left} over` : `Day ${c.day}`}
                </td>
                <td>
                  <span className={`fpod-src${c.is_manual ? " is-manual" : ""}`}>{c.is_manual || c.source !== "icegate" ? "Typed" : "ICEGATE"}</span>
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

/** The table drawn as a clean PNG (always light, for the client): shipment line on top, one row per container. */
function tableImage(s: Shipment, portLabel: string, rows: ShipmentContainer[]): Promise<Blob> {
  const scale = 2;
  const cols = [
    { label: "Container", w: 150, get: (c: ShipmentContainer) => c.container_no },
    { label: "Type", w: 56, get: (c: ShipmentContainer) => c.status ?? "—" },
    { label: "Status", w: 170, get: (c: ShipmentContainer) => c.tracking_status ?? (c.arrival_date ? "Arrived" : "Not arrived yet") },
    { label: "Arrived at FPOD", w: 120, get: (c: ShipmentContainer) => fmt(c.arrival_date) },
    { label: "Days free", w: 76, get: (c: ShipmentContainer) => String(c.free_days) },
    { label: "Free until", w: 120, get: (c: ShipmentContainer) => fmt(c.last_free_day) },
    { label: "Day", w: 110, get: (c: ShipmentContainer) => (c.day == null ? "—" : c.days_left != null && c.days_left < 0 ? `Day ${c.day} (${-c.days_left} over)` : `Day ${c.day}`) },
  ];
  const pad = 24;
  const rowH = 30;
  const width = pad * 2 + cols.reduce((n, c) => n + c.w, 0);
  const headH = 86;
  const height = headH + rowH * (rows.length + 1) + pad;
  const canvas = document.createElement("canvas");
  canvas.width = width * scale;
  canvas.height = height * scale;
  const ctx = canvas.getContext("2d")!;
  ctx.scale(scale, scale);
  const font = (w: number, size: number) => `${w} ${size}px Inter, -apple-system, "Segoe UI", Roboto, sans-serif`;

  ctx.fillStyle = "#FFFFFF";
  ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = "#D26B21";
  ctx.font = font(700, 15);
  ctx.fillText("CLARUS LOGISTICS", pad, pad + 12);
  ctx.fillStyle = "#1B1C1F";
  ctx.font = font(600, 14);
  const who = [s.job ? `Job ${s.job}` : null, s.consignee || s.client].filter(Boolean).join(" · ");
  ctx.fillText(`Container tracking · ${portLabel}${who ? ` · ${who}` : ""}`, pad, pad + 34);
  ctx.fillStyle = "#5F636A";
  ctx.font = font(400, 12);
  const asOn = new Date().toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  ctx.fillText(`BL ${s.mbl || "—"} · BE ${s.be_no || "not filed"} · as on ${asOn}`, pad, pad + 54);

  let y = headH;
  ctx.fillStyle = "#EDEDEA";
  ctx.fillRect(pad, y, width - pad * 2, rowH);
  ctx.fillStyle = "#26272B";
  ctx.font = font(600, 12);
  let x = pad;
  for (const c of cols) {
    ctx.fillText(c.label, x + 8, y + 19);
    x += c.w;
  }
  ctx.font = font(400, 12.5);
  for (const r of rows) {
    y += rowH;
    ctx.strokeStyle = "#E8E8E4";
    ctx.beginPath();
    ctx.moveTo(pad, y + rowH);
    ctx.lineTo(width - pad, y + rowH);
    ctx.stroke();
    x = pad;
    for (const c of cols) {
      const over = c.label === "Day" && r.days_left != null && r.days_left < 0;
      ctx.fillStyle = over ? "#9A3129" : "#1B1C1F";
      let text = c.get(r);
      while (ctx.measureText(text).width > c.w - 14 && text.length > 3) text = `${text.slice(0, -2)}…`;
      ctx.fillText(text, x + 8, y + 19);
      x += c.w;
    }
  }
  return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("no image"))), "image/png"));
}
