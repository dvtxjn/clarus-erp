import Toast from "./Toast";
import LoadError from "./LoadError";
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
import type { Shipment } from "./types";
import { useAuth } from "./AuthContext";
import { errorCodeLines, istTime, readableCustoms } from "./customsMail";
import CustomsReadBar from "./CustomsReadBar";
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
  const [loadErr, setLoadErr] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // tab badges: how many mails "Needs attention" / "Not matched" hold under the same filters
  const [counts, setCounts] = useState<{ attention?: number; unmatched?: number }>({});
  const load = useCallback(() => {
    const f = {
      scope,
      source: source || undefined,
      kind: kind || undefined,
      port: port || undefined,
      date_from: from || undefined,
      date_to: to || undefined,
    } as const;
    listIcegateMails({ ...f, attention: view === "attention", unmatched: view === "unmatched" })
      .then((r) => {
        setRows(r);
        setLoadErr(false);
      })
      .catch(() => setLoadErr(true));
    listIcegateMails({ ...f, attention: true, limit: 2000 })
      .then((r) => setCounts((c) => ({ ...c, attention: r.length })))
      .catch(() => undefined);
    if (isAdmin)
      listIcegateMails({ ...f, unmatched: true, limit: 2000 })
        .then((r) => setCounts((c) => ({ ...c, unmatched: r.length })))
        .catch(() => undefined);
  }, [view, scope, source, kind, port, from, to, isAdmin]);

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

  const [linking, setLinking] = useState<IcegateMail | null>(null);
  async function linkTo(m: IcegateMail, s: Shipment) {
    try {
      await linkIcegateMail(m.id, s.id);
      setMsg({ ok: true, text: `Put on job ${s.job}.` });
      setLinking(null);
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
      {linking && <JobPicker mail={linking} onPick={(s) => linkTo(linking, s)} onClose={() => setLinking(null)} />}
      <div>
        <h1>Customs mail</h1>
        <p className="field-note">
          ICEGATE and ODeX mails, matched to their shipments by BE no, job no or BL. ODeX’s DO released ticks DO; a rejected DO
          request goes to Needs attention. Acks fill the BE no; BE, OOC and gate pass copies are
          added as documents; queries and rejections go to Needs attention. Times are India time.
        </p>
      </div>

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
        <Toast ok={msg.ok} stamp={msg}>{msg.text}</Toast>
      )}

      {(isAdmin || user?.role === "import_manager") && <CustomsReadBar isAdmin={isAdmin} onRead={load} />}
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
              {(v === "attention" || v === "unmatched") && !!counts[v] && <span className="chip-count"> {counts[v]}</span>}
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

      {shown === null && loadErr ? (
        <LoadError what="customs mails" onRetry={load} />
      ) : shown === null ? (
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
                <th>BE No</th>
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
                        <button type="button" className="btn-secondary" onClick={() => setLinking(m)}>
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
  const t = readableCustoms(text);
  if (!t) return <>—</>;
  const codes = errorCodeLines(text);
  if (codes.length)
    return (
      <details className="customs-says-box">
        <summary title="Show the whole text">{codes[0]}</summary>
        <div className="customs-says-full">{[...codes.slice(1), t].join("\n")}</div>
      </details>
    );
  const firstLine = t.split("\n")[0];
  if (t.length <= 90 && firstLine === t) return <div className="customs-says-box">{t}</div>;
  return (
    <details className="customs-says-box">
      <summary title="Show the whole text">{firstLine.length > 90 ? `${firstLine.slice(0, 90)}…` : firstLine}</summary>
      <div className="customs-says-full">{t}</div>
    </details>
  );
}

/** "Link to job": search shipments by job, BE or BL; starts on the mail's own BE / BL / job so the likely match is on top. */
function JobPicker({ mail, onPick, onClose }: { mail: IcegateMail; onPick: (s: Shipment) => void; onClose: () => void }) {
  const [q, setQ] = useState(mail.be_no || mail.mbl || mail.job_no || "");
  const [found, setFound] = useState<Shipment[] | null>(null);
  useEffect(() => {
    const t = q.trim();
    if (t.length < 2) {
      setFound([]);
      return;
    }
    setFound(null);
    const timer = window.setTimeout(() => {
      listShipments({ search: t, include_archived: true })
        .then((r) => setFound(r.slice(0, 30)))
        .catch(() => setFound([]));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [q]);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div className="confirm-dialog job-picker" role="dialog" aria-modal="true" aria-labelledby="jp-title" onClick={(e) => e.stopPropagation()}>
        <h2 id="jp-title">Which job is this mail for?</h2>
        <p>{mail.label}{mail.summary ? `: ${readableCustoms(mail.summary)}` : ""}</p>
        <input autoFocus value={q} placeholder="Job, BE no or BL" aria-label="Search job, BE or BL" onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && found?.length === 1 && onPick(found[0])} />
        <ul className="job-picker-list">
          {found === null && <li className="field-note">Searching…</li>}
          {found?.length === 0 && q.trim().length >= 2 && <li className="field-note">No shipment matches.</li>}
          {found?.map((s) => (
            <li key={s.id}>
              <button type="button" onClick={() => onPick(s)}>
                <b>Job {s.job}</b> · BL {s.mbl || "—"} · BE {s.be_no || "—"}
                {s.client ? <span className="tracker-subtitle"> · {s.client}</span> : null}
              </button>
            </li>
          ))}
        </ul>
        <div className="confirm-actions">
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
