import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  addChallan,
  createOrganization,
  getDailyStatus,
  importOrganizations,
  listOrganizations,
  updateOrganization,
  uploadChallans,
} from "./api";
import type { ChallanUploadResult, DailyStatus, Organization, OrganizationInput } from "./types";

const inr = (v: string | number | null | undefined) =>
  v == null ? "—" : `₹${Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function when(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  const today = new Date().toDateString() === d.toDateString();
  const time = d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
  return today ? `today ${time}` : `${d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" })} ${time}`;
}

function errorText(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : "Something went wrong — please try again.";
}

/**
 * Landing-page cards for the two things proformas depend on day to day:
 * today's duty challan list (customs duty interest) and the organization
 * repository (Bill To details).
 */
export default function DailyUpdates() {
  const [status, setStatus] = useState<DailyStatus | null>(null);
  const refresh = () => {
    getDailyStatus().then(setStatus).catch(() => setStatus(null));
  };
  useEffect(refresh, []);
  if (!status) return null;
  return (
    <div className="daily-updates">
      <ChallanCard status={status} onChange={refresh} />
      <OrganizationsCard status={status} onChange={refresh} />
    </div>
  );
}

function ChallanCard({ status, onChange }: { status: DailyStatus; onChange: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ChallanUploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [manual, setManual] = useState(false);
  const [beNo, setBeNo] = useState("");
  const [due, setDue] = useState("");
  const [showAwaiting, setShowAwaiting] = useState(false);
  const awaiting = status.awaiting_challan;

  async function run(action: () => Promise<ChallanUploadResult>) {
    setBusy(true);
    setError(null);
    try {
      setResult(await action());
      onChange();
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function onFile(file: File | undefined) {
    if (file) await run(() => uploadChallans(file));
    if (fileRef.current) fileRef.current.value = "";
  }

  async function onManual(e: FormEvent) {
    e.preventDefault();
    if (!beNo.trim() || !due) return;
    if (await run(() => addChallan({ be_no: beNo.trim(), due_amount: Number(due) }))) {
      setBeNo("");
      setDue("");
    }
  }

  const fresh = status.challans_updated_today;
  return (
    <section className={`daily-card${fresh ? "" : " daily-card-due"}`}>
      <div className="daily-card-head">
        <div>
          <h3>Duty challans</h3>
          <div className="daily-status">
            <span className={`daily-dot ${fresh ? "ok" : "due"}`} />
            {fresh
              ? `Updated ${when(status.challans_last_uploaded_at)} · ${status.challans_in_last_upload} BE(s)`
              : `Not updated today (last: ${when(status.challans_last_uploaded_at)}) — upload today's list so proforma interest is current.`}
          </div>
        </div>
        <div className="daily-actions">
          <input ref={fileRef} type="file" accept=".xlsx" hidden onChange={(e) => onFile(e.target.files?.[0])} />
          <button className="btn-secondary" onClick={() => fileRef.current?.click()} disabled={busy}>
            {busy ? "Reading…" : "Upload challan list"}
          </button>
          <button className="btn-secondary" onClick={() => setManual((m) => !m)}>
            Enter by hand
          </button>
        </div>
      </div>
      <p className="daily-help">
        Upload the ICEGATE pending-challan export (.xlsx, downloaded from ICEGATE by hand: Doc no., Due Amount…). Interest = Due Amount − the BE's total duty; it's
        added to Customs Duty when a proforma is filled or refreshed.
      </p>
      {awaiting.length > 0 && (
        <div className="awaiting-challan" role="alert">
          <button type="button" className="link-button" onClick={() => setShowAwaiting((v) => !v)}>
            {awaiting.length} ongoing BE{awaiting.length > 1 ? "s" : ""} with no challan or OOC copy — interest unknown on
            their proformas. {showAwaiting ? "Hide" : "Show"}
          </button>
          {showAwaiting && (
            <ul>
              {awaiting.map((a) => (
                <li key={a.id}>
                  <Link to={`/shipments/${a.id}`}>{a.job ? `Job ${a.job}` : a.mbl}</Link> · BE {a.be_no}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {manual && (
        <form className="daily-inline-form" onSubmit={onManual}>
          <input placeholder="BE No" value={beNo} onChange={(e) => setBeNo(e.target.value)} required />
          <input placeholder="Due amount (₹)" type="number" step="0.01" min="0" value={due} onChange={(e) => setDue(e.target.value)} required />
          <button type="submit" disabled={busy}>
            Save
          </button>
        </form>
      )}
      {error && <div role="alert" className="invoice-error">{error}</div>}
      {result && (
        <div className="fill-result">
          <div>
            <strong>{result.rows} BE(s) read.</strong> {result.matched.length} matched to shipments
            {result.unmatched.length > 0 && ` · ${result.unmatched.length} not in the tracker yet (picked up once the BE No is added)`}.
          </div>
          {result.matched.length > 0 && (
            <ul>
              {result.matched.map((m) => (
                <li key={m.be_no}>
                  <Link to={`/shipments/${m.shipment_id}`}>{m.job ? `Job ${m.job}` : m.mbl}</Link> · BE {m.be_no} · due {inr(m.due_amount)}
                  {m.interest == null ? " · no BE duty yet" : Number(m.interest) > 0 ? ` · interest ${inr(m.interest)}` : " · no interest"}
                </li>
              ))}
            </ul>
          )}
          {result.note && <div className="field-note">{result.note}</div>}
          <button className="btn-secondary" onClick={() => setResult(null)}>
            Dismiss
          </button>
        </div>
      )}
    </section>
  );
}

function OrganizationsCard({ status, onChange }: { status: DailyStatus; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [editing, setEditing] = useState<Organization | "new" | null>(null);
  const [search, setSearch] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = () => listOrganizations().then(setOrgs);
  useEffect(() => {
    if (open) load();
  }, [open]);

  async function onImport(file: File | undefined) {
    if (!file) return;
    try {
      const r = await importOrganizations(file);
      setMsg(`Imported: ${r.created} new, ${r.updated} updated.`);
      load();
      onChange();
    } catch (e) {
      setMsg(errorText(e));
    }
    if (fileRef.current) fileRef.current.value = "";
  }

  const q = search.trim().toLowerCase();
  const shown = orgs.filter((o) => !q || [o.name, o.short_names, o.gstin].some((x) => x?.toLowerCase().includes(q)));

  return (
    <section className="daily-card">
      <div className="daily-card-head">
        <div>
          <h3>Organization repository</h3>
          <div className="daily-status">
            <span className={`daily-dot ${status.organizations_updated_today ? "ok" : "idle"}`} />
            {status.organizations} parties · last updated {when(status.organizations_last_updated_at)}
          </div>
        </div>
        <div className="daily-actions">
          <button
            onClick={() => {
              setOpen(true);
              setEditing("new");
            }}
          >
            + Add organization
          </button>
          <button className="btn-secondary" onClick={() => setOpen((o) => !o)}>
            {open ? "Hide list" : "View list"}
          </button>
        </div>
      </div>
      <p className="daily-help">Bill To details come from here (matched on the BE importer's name); the BL consignee is the party holding the BE's AD code.</p>
      {msg && <div className="field-note">{msg}</div>}
      {editing && (
        <OrganizationForm
          org={editing === "new" ? null : editing}
          onSaved={() => {
            setEditing(null);
            load();
            onChange();
          }}
          onCancel={() => setEditing(null)}
        />
      )}
      {open && (
        <div className="org-list">
          <div className="org-list-bar">
            <input placeholder="Search name / GSTIN…" value={search} onChange={(e) => setSearch(e.target.value)} />
            <input ref={fileRef} type="file" accept=".xlsx" hidden onChange={(e) => onImport(e.target.files?.[0])} />
            <button className="btn-secondary" onClick={() => fileRef.current?.click()} title="Filing software's 'Organization List' export">
              Import Excel
            </button>
          </div>
          {shown.length === 0 ? (
            <p className="tracker-subtitle">No organizations yet.</p>
          ) : (
            <ul className="simple-list">
              {shown.map((o) => (
                <li key={o.id}>
                  <span>
                    <strong>{o.name}</strong>
                    {o.short_names && <span className="tracker-subtitle"> · {o.short_names}</span>}
                    {o.gstin && <span className="tracker-subtitle"> · {o.gstin}</span>}
                  </span>
                  <button className="btn-secondary btn-small" onClick={() => setEditing(o)}>
                    Edit
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

const EMPTY: OrganizationInput = {
  name: "",
  short_names: null,
  ad_code: null,
  gstin: null,
  pan: null,
  iec: null,
  address: null,
  state: null,
  email: null,
  phone: null,
  is_active: true,
  line_in_cost_inclusion: true,
};

const FIELDS: { key: keyof OrganizationInput; label: string; placeholder?: string; wide?: boolean }[] = [
  { key: "name", label: "Registered name *", placeholder: "MAHRISHI RECYCLERS", wide: true },
  { key: "short_names", label: "Names used in the tracker", placeholder: "Mahrishi (comma-separated)", wide: true },
  { key: "address", label: "Address", wide: true },
  { key: "gstin", label: "GSTIN" },
  { key: "pan", label: "PAN" },
  { key: "state", label: "State", placeholder: "Maharashtra [27]" },
  { key: "iec", label: "IEC" },
  { key: "ad_code", label: "AD Code", placeholder: "7 digits" },
  { key: "email", label: "Email" },
  { key: "phone", label: "Phone" },
];

/** Add / edit one organization. `initialName` pre-fills a new entry's name (e.g. the BE importer on a proforma). */
export function OrganizationForm({
  org,
  initialName,
  onSaved,
  onCancel,
}: {
  org: Organization | null;
  initialName?: string;
  onSaved: (o: Organization) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<OrganizationInput>(() =>
    org ? { ...EMPTY, ...org } : { ...EMPTY, name: initialName ?? "" },
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const payload = { ...form, ad_code: form.ad_code?.trim() || null };
    try {
      onSaved(org ? await updateOrganization(org.id, payload) : await createOrganization(payload));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="org-form" onSubmit={save}>
      {FIELDS.map((f) => (
        <label key={f.key} className={f.wide ? "wide" : undefined}>
          <span>{f.label}</span>
          <input
            value={(form[f.key] as string | null) ?? ""}
            placeholder={f.placeholder}
            required={f.key === "name"}
            pattern={f.key === "ad_code" ? "\\d{7}" : undefined}
            onChange={(e) => setForm({ ...form, [f.key]: e.target.value || (f.key === "name" ? "" : null) })}
          />
        </label>
      ))}
      <label className="toggle-row wide" title="e.g. Harekrishna Rubber. Each shipment can still switch it on.">
        <input
          type="checkbox"
          checked={!form.line_in_cost_inclusion}
          onChange={(e) => setForm({ ...form, line_in_cost_inclusion: !e.target.checked })}
        />
        <span>Shipping line invoices NOT in cost inclusion (on shipments involving this party)</span>
      </label>
      {error && <div role="alert" className="invoice-error wide">{error}</div>}
      <div className="org-form-actions wide">
        <button type="submit" disabled={saving}>
          {org ? "Save changes" : "Add organization"}
        </button>
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
