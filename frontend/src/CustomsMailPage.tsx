import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  icegateMailKinds,
  importIcegateMails,
  linkIcegateMail,
  listIcegateMails,
  listShipments,
  resolveIcegateMail,
  type IcegateMail,
} from "./api";
import { useAuth } from "./AuthContext";
import { istTime } from "./customsMail";
import IcegateLoginPanel from "./IcegateLoginPanel";
import { formatPort, usePorts } from "./ports";

type View = "all" | "attention" | "unmatched";

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Something went wrong — try again.";
}

/**
 * Customs mail (client, 2026-09-30, P1): every ICEGATE mail read into the ERP — B/E Ack, Neg Ack, Query,
 * Examination Order, Processed B/E, Out of Charge, Gate Pass, eSANCHIT, login OTPs — matched to shipments.
 * Until the mailbox is read automatically, the admin drops the mails here (.eml files, or Gmail's zip).
 */
export default function CustomsMailPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [params, setParams] = useSearchParams();
  const view = (params.get("view") as View) || "all";
  const [q, setQ] = useState(params.get("q") ?? "");
  // filters live in the URL (shareable, survive a reload); scope defaults to live shipments — the old
  // inbox brought years of mails for jobs no longer in the tracker (client, 2026-09-30)
  const scope = (params.get("scope") as "live" | "history" | "all") || "live";
  const kind = params.get("kind") ?? "";
  const source = (params.get("source") as "icegate" | "odex" | null) ?? "";
  const port = params.get("port") ?? "";
  const from = params.get("from") ?? "";
  const to = params.get("to") ?? "";
  const clientF = params.get("client") ?? "";
  const [kinds, setKinds] = useState<{ kind: string; label: string }[]>([]);
  const ports = usePorts();
  const [rows, setRows] = useState<IcegateMail[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    listIcegateMails({
      attention: view === "attention",
      unmatched: view === "unmatched",
      scope,
      source: source || undefined,
      kind: kind || undefined,
      port: port || undefined,
      date_from: from || undefined,
      date_to: to || undefined,
    })
      .then(setRows)
      .catch(() => setRows([]));
  }, [view, scope, source, kind, port, from, to]);

  useEffect(() => {
    icegateMailKinds().then(setKinds).catch(() => setKinds([]));
  }, []);

  function setFilter(key: string, value: string) {
    const p = new URLSearchParams(params);
    if (value) p.set(key, value);
    else p.delete(key);
    setParams(p, { replace: true });
  }
  const filtered = !!(kind || source || port || from || to || clientF || scope !== "live");

  useEffect(() => {
    load();
    const t = window.setInterval(load, 60_000); // OTPs are only useful fresh
    return () => window.clearInterval(t);
  }, [load]);

  function setView(v: View) {
    const p = new URLSearchParams(params);
    if (v === "all") p.delete("view");
    else p.set("view", v);
    setParams(p, { replace: true });
  }

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await importIcegateMails(Array.from(files));
      setMsg({
        ok: true,
        text: `${r.new} new mail${r.new === 1 ? "" : "s"} read${r.duplicates ? ` · ${r.duplicates} already read` : ""}${
          r.ignored ? ` · ${r.ignored} not from ICEGATE (skipped)` : ""
        } · ${r.matched} matched to shipments · ${r.attention} need attention`,
      });
      load();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    } finally {
      setBusy(false);
    }
  }

  async function done(m: IcegateMail) {
    try {
      const x = await resolveIcegateMail(m.id);
      setRows((r) => r?.map((y) => (y.id === x.id ? x : y)) ?? null);
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  }

  async function linkTo(m: IcegateMail) {
    const job = window.prompt(`Which job is this mail for?\n${m.label}: ${m.summary ?? ""}`)?.trim();
    if (!job) return;
    try {
      const found = (await listShipments({ search: job, include_archived: true })).filter((s) => s.job === job);
      if (found.length !== 1) {
        setMsg({ ok: false, text: found.length ? `More than one shipment has job ${job}.` : `No shipment with job ${job}.` });
        return;
      }
      await linkIcegateMail(m.id, found[0].id);
      setMsg({ ok: true, text: `Put on job ${job}.` });
      load();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  }

  const clients = useMemo(
    () => Array.from(new Set((rows ?? []).map((m) => m.client).filter((c): c is string => !!c))).sort(),
    [rows],
  );

  const shown = useMemo(() => {
    const t = q.trim().toUpperCase();
    const byClient = clientF ? (rows ?? []).filter((m) => m.client === clientF) : rows;
    if (!byClient || !t) return byClient;
    return byClient.filter((m) =>
      [m.be_no, m.job_no, m.shipment_job, m.mbl, m.shipment_mbl, m.client, m.label, m.summary].some((v) =>
        (v ?? "").toUpperCase().includes(t),
      ),
    );
  }, [rows, q, clientF]);

  return (
    <div className="rates-page customs-page">
      <div>
        <h1>Customs mail</h1>
        <p className="field-note">
          ICEGATE and ODeX mails, matched to their shipments by BE no, job no or BL. ODeX’s DO released ticks DO; a rejected DO
          request goes to Needs attention. Acks fill the BE no; BE, OOC and gate pass copies are
          added as documents; queries and rejections go to Needs attention. Times are India time.
        </p>
      </div>

      {(isAdmin || user?.role === "import_manager") && <IcegateLoginPanel isAdmin={isAdmin} />}

      {isAdmin && (
        <label className={`customs-drop${busy ? " is-busy" : ""}`}>
          <input
            type="file"
            multiple
            accept=".eml,.zip,message/rfc822,application/zip"
            disabled={busy}
            onChange={(e) => {
              upload(e.target.files);
              e.target.value = "";
            }}
          />
          <span>{busy ? "Reading mails…" : "Add mails: choose .eml files or the zip from Gmail (Forward as attachment → Download all)"}</span>
        </label>
      )}
      {msg && (
        <div role="status" aria-live="polite" className={`grid-toast ${msg.ok ? "grid-toast-ok" : "grid-toast-error"}`}>
          {msg.text}
        </div>
      )}

      <div className="customs-bar">
        <div className="seg-switch" role="group" aria-label="Show">
          {(
            [
              ["all", "All"],
              ["attention", "Needs attention"],
              ...(isAdmin ? [["unmatched", "Not matched"]] : []),
            ] as [View, string][]
          ).map(([v, label]) => (
            <button key={v} type="button" className={view === v ? "on" : ""} aria-pressed={view === v} onClick={() => setView(v)}>
              {label}
            </button>
          ))}
        </div>
        <input
          type="search"
          aria-label="Search mails"
          placeholder="BE no, job, BL, client…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          spellCheck={false}
        />
      </div>
      <div className="customs-filters">
        <label>
          <span>Shipments</span>
          <select value={scope} onChange={(e) => setFilter("scope", e.target.value === "live" ? "" : e.target.value)}>
            <option value="live">In the tracker now</option>
            <option value="history">History (old / gone)</option>
            <option value="all">Everything</option>
          </select>
        </label>
        <label>
          <span>From</span>
          <select value={source} onChange={(e) => setFilter("source", e.target.value)}>
            <option value="">ICEGATE and ODeX</option>
            <option value="icegate">ICEGATE</option>
            <option value="odex">ODeX (DO / line invoices)</option>
          </select>
        </label>
        <label>
          <span>Type</span>
          <select value={kind} onChange={(e) => setFilter("kind", e.target.value)}>
            <option value="">All types</option>
            {kinds.filter((k) => !source || (source === "odex") === k.kind.startsWith("odex")).map((k) => (
              <option key={k.kind} value={k.kind}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Port</span>
          <select value={port} onChange={(e) => setFilter("port", e.target.value)}>
            <option value="">All ports</option>
            {ports.map((p) => (
              <option key={p.code} value={p.code}>
                {formatPort(p.code, ports)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Client</span>
          <select value={clientF} onChange={(e) => setFilter("client", e.target.value)}>
            <option value="">All clients</option>
            {clients.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Received from</span>
          <input type="date" value={from} onChange={(e) => setFilter("from", e.target.value)} />
        </label>
        <label>
          <span>Received to</span>
          <input type="date" value={to} onChange={(e) => setFilter("to", e.target.value)} />
        </label>
        {filtered && (
          <button
            type="button"
            className="link-button"
            onClick={() => {
              const p = new URLSearchParams(params);
              ["scope", "source", "kind", "port", "from", "to", "client"].forEach((k) => p.delete(k));
              setParams(p, { replace: true });
            }}
          >
            Clear filters
          </button>
        )}
        {rows && (
          <span className="field-note">
            {shown?.length ?? 0} mail{shown?.length === 1 ? "" : "s"}
            {rows.length >= 300 ? " (newest 300 — narrow the filters to see older)" : ""}
          </span>
        )}
      </div>

      {shown === null ? (
        <div className="tracker-empty">Loading…</div>
      ) : shown.length === 0 ? (
        <div className="tracker-empty">
          {filtered
            ? "No mails match these filters."
            : view === "attention"
              ? "Nothing needs attention."
              : view === "unmatched"
                ? "Every mail is on its shipment."
                : "No mails for shipments in the tracker — see History for older ones."}
        </div>
      ) : (
        <div className="tracker-grid-wrap">
          <table className="tracker-grid customs-table">
            <thead>
              <tr>
                <th>Received</th>
                <th>Type</th>
                <th>Job</th>
                <th>BE no</th>
                <th>BL</th>
                <th>Client</th>
                <th>What it says</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {shown.map((m) => {
                const open = m.attention && !m.resolved_at;
                const otp = m.kind === "otp" ? (m.detail?.otp as string | undefined) : undefined;
                return (
                  <tr key={m.id} className={[open ? "is-open" : "", m.live ? "" : "is-history"].join(" ").trim() || undefined}>
                    <td className="num">{istTime(m.received_at)}</td>
                    <td>
                      {m.label}
                      {open && <span className="customs-flag">Needs attention</span>}
                    </td>
                    <td>
                      {m.shipment_id ? (
                        <Link to={`/shipments/${m.shipment_id}?tab=customs`}>{m.shipment_job ? `Job ${m.shipment_job}` : "Open"}</Link>
                      ) : m.kind === "otp" ? (
                        "—"
                      ) : (
                        <span className="customs-unmatched">{m.job_no ? `Job ${m.job_no}?` : "Not matched"}</span>
                      )}
                    </td>
                    <td className="num" translate="no">{m.shipment_be_no || m.be_no || "—"}</td>
                    <td translate="no">{m.shipment_mbl || m.mbl || "—"}</td>
                    <td>{m.client || "—"}</td>
                    <td className="customs-says">
                      {otp ? (
                        <span className="customs-otp">
                          <b translate="no">{otp}</b> valid 10 min from {istTime(m.received_at)}
                        </span>
                      ) : m.kind === "otp" ? (
                        m.detail?.otp_expired ? "Expired" : "Admin only"
                      ) : (
                        <Says text={m.summary} />
                      )}
                      {m.resolved_at && m.attention && <span className="customs-done">Done{m.resolved_note ? ` · ${m.resolved_note}` : ""}</span>}
                    </td>
                    <td className="customs-actions">
                      {open && (
                        <button type="button" className="btn-secondary" onClick={() => done(m)}>
                          Mark done
                        </button>
                      )}
                      {isAdmin && !m.shipment_id && m.kind !== "otp" && (
                        <button type="button" className="btn-secondary" onClick={() => linkTo(m)}>
                          Link to job…
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** The mail's text in a fixed-width cell: short ones as they are, long ones cut to one line that opens on click. */
function Says({ text }: { text: string | null | undefined }) {
  const t = (text ?? "").trim();
  if (!t) return <>—</>;
  const firstLine = t.split("\n")[0];
  if (t.length <= 90 && firstLine === t) return <div className="customs-says-box">{t}</div>;
  return (
    <details className="customs-says-box">
      <summary title="Show the whole text">{firstLine.length > 90 ? `${firstLine.slice(0, 90)}…` : firstLine}</summary>
      <div className="customs-says-full">{t}</div>
    </details>
  );
}
