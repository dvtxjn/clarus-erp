import { fmtWhen } from "./dates";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { getSettings, getSystemStatus, setSetting, type AppSettings, type CompanySettings, type SystemStatus } from "./api";
import { EInvoicing, InvoiceNumbering, TdsRateSwitch } from "./RatesPage";
import SheetsMirrorSettings from "./SheetsMirrorSettings";
import MailboxSettings from "./MailboxSettings";
import AutoRulesSettings from "./AutoRulesSettings";

/**
 * Settings (client, 2026-09-30, P0): what used to be fixed in the code — company and bank
 * details, invoice wording, e-invoicing, numbering — the admin changes here. Storage and
 * backups are shown (they're set on the server). Admin only.
 */
function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Couldn't save.";
}

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="settings-section">
      <div className="settings-head">
        <h2>{title}</h2>
        {hint && <p className="tracker-subtitle">{hint}</p>}
      </div>
      <div className="settings-body">{children}</div>
    </section>
  );
}

// blocks with unsaved edits: leaving the page (tab close or an in-app link) asks first (UX pass 2026-09-30)
const unsaved = new Set<string>();
function useLeaveGuard() {
  useEffect(() => {
    const onUnload = (e: BeforeUnloadEvent) => {
      if (unsaved.size) e.preventDefault();
    };
    const onClick = (e: MouseEvent) => {
      const a = (e.target as HTMLElement | null)?.closest?.("a[href]");
      if (!unsaved.size || !a || e.defaultPrevented || e.metaKey || e.ctrlKey || (a as HTMLAnchorElement).target === "_blank") return;
      if (!window.confirm("You have unsaved changes in Settings. Leave without saving?")) {
        e.preventDefault();
        e.stopPropagation();
      } else unsaved.clear();
    };
    window.addEventListener("beforeunload", onUnload);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("beforeunload", onUnload);
      document.removeEventListener("click", onClick, true);
      unsaved.clear();
    };
  }, []);
}

/** Save / saved state for one block. */
function useSave<T>(key: keyof AppSettings, initial: T | undefined, onSaved: (s: AppSettings) => void) {
  const [value, setValue] = useState<T | undefined>(initial);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => setValue(initial), [initial]);
  const dirty = JSON.stringify(value) !== JSON.stringify(initial);
  useEffect(() => {
    if (dirty) unsaved.add(String(key));
    else unsaved.delete(String(key));
    return () => void unsaved.delete(String(key));
  }, [dirty, key]);
  const save = async (override?: T) => {
    setBusy(true);
    setMsg(null);
    try {
      onSaved(await setSetting(key, (override ?? value) as AppSettings[typeof key]));
      setMsg({ ok: true, text: "Saved — new invoices and PDFs use it." });
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    } finally {
      setBusy(false);
    }
  };
  return { value, setValue, dirty, save, busy, msg };
}

function SaveBar({ dirty, busy, msg, onSave, onReset }: { dirty: boolean; busy: boolean; msg: { ok: boolean; text: string } | null; onSave: () => void; onReset: () => void }) {
  return (
    <div className={`settings-save${dirty ? " is-dirty" : ""}`}>
      <button disabled={!dirty || busy} onClick={onSave}>
        {busy ? "Saving…" : "Save"}
      </button>
      {dirty && (
        <>
          <button className="btn-secondary" onClick={onReset}>
            Undo changes
          </button>
          <span className="settings-unsaved">Unsaved changes</span>
        </>
      )}
      {msg && <span role="status" className={msg.ok ? "settings-ok" : "auth-error"}>{msg.text}</span>}
    </div>
  );
}

export default function SettingsPage() {
  const [s, setS] = useState<AppSettings | null>(null);
  const [sys, setSys] = useState<SystemStatus | null>(null);
  useLeaveGuard();
  useEffect(() => {
    getSettings().then(setS);
    getSystemStatus().then(setSys).catch(() => setSys(null));
  }, []);
  if (!s) return <div className="tracker-empty">Loading…</div>;
  return (
    <div className="dashboard-page settings-page">
      <div className="dash-head">
        <h1>Settings</h1>
        <span className="tracker-subtitle">Only the admin sees and changes these</span>
      </div>
      <CompanyBlock s={s} onSaved={setS} />
      <BankBlock s={s} onSaved={setS} />
      <TextBlock s={s} onSaved={setS} />
      <Section title="Invoicing" hint="E-invoicing, where the invoice numbers continue from, and TDS rates. Rates and licences are on the Rates page.">
        <EInvoicing canEdit />
        <InvoiceNumbering canEdit />
        <TdsRateSwitch canEdit />
        <p className="field-note">
          Standard rates, licences and HSS rules: <Link to="/rates">Rates</Link>.
        </p>
      </Section>
      <Section title="ICEGATE & ODeX mailbox" hint="ICEGATE and ODeX (DO / line invoice) mails read automatically. “Check mail now” is on the Customs mail page.">
        <MailboxSettings />
      </Section>
      <Section title="Automatic rules" hint="What the ERP updates by itself from mails and ICEGATE — switch any rule off, or add your own.">
        <AutoRulesSettings />
      </Section>
      <Section title="Google Sheets copy" hint="A view-only copy of the tracker, so the office can still see shipments if the ERP is down.">
        <SheetsMirrorSettings />
      </Section>
      <Section title="Storage & backups" hint="Set on the server — shown here so you can check them.">
        {sys ? (
          <div className="settings-grid">
            <span className="field-label">Files kept in</span>
            <span>{sys.storage === "drive" ? "Google Drive (Shared Drive)" : "This computer (local)"}</span>
            {Object.entries(sys.drive_folders).map(([k, v]) => (
              <SysRow key={k} label={`Drive: ${k}`} value={v ? <a href={v} target="_blank" rel="noreferrer">Open folder ↗</a> : "—"} />
            ))}
            <span className="field-label">Last backup</span>
            <span>
              {sys.backups.last_ok_at
                ? `${fmtWhen(sys.backups.last_ok_at, true)} (${sys.backups.last_ok_age_hours} h ago)${sys.backups.in_drive ? " · in Drive" : ""}`
                : "None yet"}
            </span>
            {sys.backups.warnings.length > 0 && (
              <>
                <span className="field-label">Backup warnings</span>
                <span className="auth-error">{sys.backups.warnings.join(" ")}</span>
              </>
            )}
            <span className="field-label">Running as</span>
            <span>
              {sys.environment}
              {sys.public_url ? ` · ${sys.public_url}` : ""}
            </span>
          </div>
        ) : (
          <p className="tracker-subtitle">Couldn't read the server status.</p>
        )}
      </Section>
      <Section title="Users & permissions" hint="Who can log in, their role, and passwords (set by the admin only).">
        <div className="settings-grid">
          <span className="field-label">Admin</span>
          <span>Everything, incl. invoicing, rates, settings, restoring deleted items.</span>
          <span className="field-label">Import manager / staff</span>
          <span>Shipments, documents, tracker — no invoicing, rates or settings.</span>
        </div>
        <p>
          <Link to="/users">Manage users →</Link>
        </p>
      </Section>
    </div>
  );
}

function SysRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <>
      <span className="field-label">{label}</span>
      <span>{value}</span>
    </>
  );
}

function CompanyBlock({ s, onSaved }: { s: AppSettings; onSaved: (s: AppSettings) => void }) {
  const b = useSave<CompanySettings>("company", s.company, onSaved);
  const c = b.value ?? s.company;
  const set = (k: keyof CompanySettings, v: string) => b.setValue({ ...c, [k]: v });
  const field = (k: keyof CompanySettings, label: string, wide = false) => (
    <label className={`final-field${wide ? " settings-wide" : ""}`}>
      <span>{label}</span>
      <input value={(c[k] as string) ?? ""} onChange={(e) => set(k, e.target.value)} />
    </label>
  );
  return (
    <Section title="Company" hint="Printed at the top of every proforma and final invoice.">
      <div className="settings-form">
        {field("name", "Company name", true)}
        <label className="final-field settings-wide">
          <span>Address (one line per row)</span>
          <textarea
            rows={Math.max(2, c.address_lines.length + 1)}
            value={c.address_lines.join("\n")}
            onChange={(e) => b.setValue({ ...c, address_lines: e.target.value.split("\n") })}
          />
        </label>
        {field("gstin", "GSTIN")}
        {field("pan", "PAN")}
        {field("cin", "CIN / LLPIN")}
        {field("state_code", "State code")}
        {field("state", "State")}
        {field("email", "Email")}
        {field("phone", "Phone")}
      </div>
      <SaveBar
        dirty={b.dirty}
        busy={b.busy}
        msg={b.msg}
        onSave={() => b.save({ ...c, address_lines: c.address_lines.map((x) => x.trim()).filter(Boolean), gstin: c.gstin.trim().toUpperCase(), pan: c.pan.trim().toUpperCase() })}
        onReset={() => b.setValue(s.company)}
      />
    </Section>
  );
}

function BankBlock({ s, onSaved }: { s: AppSettings; onSaved: (s: AppSettings) => void }) {
  const b = useSave<[string, string][]>("bank", s.bank, onSaved);
  const rows = b.value ?? s.bank;
  const setRow = (i: number, j: 0 | 1, v: string) =>
    b.setValue(rows.map((r, k) => (k === i ? ((j === 0 ? [v, r[1]] : [r[0], v]) as [string, string]) : r)));
  return (
    <Section title="Bank details" hint="Printed on every invoice for payment.">
      <div className="settings-rows">
        {rows.map((r, i) => (
          <div className="settings-row" key={i}>
            <input value={r[0]} placeholder="Label" onChange={(e) => setRow(i, 0, e.target.value)} />
            <input value={r[1]} placeholder="Value" onChange={(e) => setRow(i, 1, e.target.value)} />
            <button type="button" className="link-button link-danger" aria-label="Remove row" onClick={() => b.setValue(rows.filter((_, k) => k !== i))}>
              ✕
            </button>
          </div>
        ))}
        <button type="button" className="link-button" onClick={() => b.setValue([...rows, ["", ""]])}>
          + row
        </button>
      </div>
      <SaveBar dirty={b.dirty} busy={b.busy} msg={b.msg} onSave={() => b.save(rows.filter((r) => r[0].trim() || r[1].trim()))} onReset={() => b.setValue(s.bank)} />
    </Section>
  );
}

function ListEditor({ label, keyName, s, onSaved }: { label: string; keyName: "proforma_notes" | "final_terms"; s: AppSettings; onSaved: (s: AppSettings) => void }) {
  const b = useSave<string[]>(keyName, s[keyName], onSaved);
  const v = b.value ?? s[keyName];
  return (
    <div className="settings-list">
      <label className="final-field">
        <span>{label} (one per line)</span>
        <textarea rows={Math.max(3, v.length + 1)} value={v.join("\n")} onChange={(e) => b.setValue(e.target.value.split("\n"))} />
      </label>
      <SaveBar
        dirty={b.dirty}
        busy={b.busy}
        msg={b.msg}
        onSave={() => b.save(v.map((x) => x.trim()).filter(Boolean))}
        onReset={() => b.setValue(s[keyName])}
      />
    </div>
  );
}

function TextBlock({ s, onSaved }: { s: AppSettings; onSaved: (s: AppSettings) => void }) {
  return (
    <Section title="Invoice wording" hint="The notes on proformas and the terms on final invoices.">
      <ListEditor label="Proforma notes" keyName="proforma_notes" s={s} onSaved={onSaved} />
      <ListEditor label="Final invoice terms" keyName="final_terms" s={s} onSaved={onSaved} />
    </Section>
  );
}
