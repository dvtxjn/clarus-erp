import { useEffect, useState, type FormEvent } from "react";
import {
  createCharge,
  deletePricingRule,
  getInvoiceCounters,
  setInvoiceCounter,
  listAllCharges,
  listLicences,
  listPricingRules,
  saveLicence,
  savePricingRule,
  updateCharge,
} from "./api";
import { usePorts } from "./ports";
import { useSearchParams } from "react-router-dom";
import { useConfirm } from "./ConfirmDialog";
import { useAuth } from "./AuthContext";
import type { ChargeCategory, ChargeMasterEntry, Licence, LicenceRate, PricingRule, PricingRuleLine } from "./types";

const SECTIONS: Record<ChargeCategory, string> = {
  service: "Billed by Clarus",
  reimbursement: "Reimbursement (at actuals)",
  royalty: "Royalty",
  cost_inclusion: "Cost Inclusion",
};
const BASIS: Record<ChargeMasterEntry["calculation_basis"], string> = {
  flat: "Flat",
  per_container: "Per container",
  per_kg: "Per kg",
};
// read from documents / worked out by the app — no standard rate to set
const FROM_DOCUMENTS: Record<string, string> = {
  CD: "from BE / challan",
  SD: "from the port formula",
  CFS: "from the CFS invoice",
  DO: "from the liner invoice",
  GSTD: "worked out from the bill rate",
};

function errorText(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : "Couldn't save — please try again.";
}

/**
 * Standard rates (charge master). A charge's standard rate fills new proforma
 * lines; it can still be changed on each proforma. Changing a rate here doesn't
 * touch proformas already made.
 */
export default function RatesPage() {
  const { user } = useAuth();
  const canEdit = user?.role === "admin";
  const [charges, setCharges] = useState<ChargeMasterEntry[] | null>(null);
  const [showRetired, setShowRetired] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [adding, setAdding] = useState(false);
  // one section at a time instead of one long page (design refresh, 2026-09-29)
  const [params, setParams] = useSearchParams();
  const tab = (["standard", "licences", "hss", "numbering"] as const).find((t) => t === params.get("tab")) ?? "standard";

  useEffect(() => {
    listAllCharges().then(setCharges);
  }, []);

  async function save(c: ChargeMasterEntry, changes: Parameters<typeof updateCharge>[1], label: string) {
    try {
      const saved = await updateCharge(c.id, changes);
      setCharges((prev) => prev?.map((x) => (x.id === saved.id ? saved : x)) ?? prev);
      setMessage({ kind: "ok", text: `Saved ${label} for ${saved.name}` });
    } catch (e) {
      setMessage({ kind: "error", text: errorText(e) });
    }
  }

  if (!charges) return <div className="tracker-empty">Loading…</div>;
  const shown = charges.filter((c) => showRetired || c.is_active);

  return (
    <div className="rates-page">
      <h1>Rates</h1>
      <div className="detail-tabs rates-tabs">
        {(
          [
            ["standard", "Standard rates"],
            ["licences", "Licences"],
            ["hss", "HSS rules"],
            ["numbering", "Invoice numbering"],
          ] as const
        ).map(([id, label]) => (
          <button key={id} className={tab === id ? "tab active" : "tab"} onClick={() => setParams(id === "standard" ? {} : { tab: id })}>
            {label}
          </button>
        ))}
      </div>
      {tab === "standard" && (
      <>
      <div className="rates-head">
        <div>
          <p className="tracker-subtitle">
            The standard rate fills in when a charge is added to a proforma — it can still be changed on each proforma.
            Changing it here doesn't alter proformas already made.
            {!canEdit && " Only an admin can change rates."}
          </p>
        </div>
        <div className="rates-actions">
          <label className="toggle-row">
            <span>Show retired</span>
            <input type="checkbox" checked={showRetired} onChange={(e) => setShowRetired(e.target.checked)} />
          </label>
          {canEdit && <button onClick={() => setAdding((a) => !a)}>{adding ? "Close" : "+ Add charge"}</button>}
        </div>
      </div>
      {message && <div className={message.kind === "ok" ? "grid-toast grid-toast-ok" : "grid-toast grid-toast-error"}>{message.text}</div>}
      {adding && (
        <NewCharge
          onCreated={(c) => {
            setCharges((prev) => [...(prev ?? []), c].sort((a, b) => a.name.localeCompare(b.name)));
            setMessage({ kind: "ok", text: `Added ${c.name}` });
            setAdding(false);
          }}
          onError={(text) => setMessage({ kind: "error", text })}
        />
      )}
      <div className="tracker-grid-wrap">
        <table className="rates-table">
          <thead>
            <tr>
              <th>Charge</th>
              <th>Code</th>
              <th>Section</th>
              <th>Basis</th>
              <th>SAC</th>
              <th className="num">GST %</th>
              <th className="num">Standard rate (₹)</th>
              <th>Active</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((c) => {
              const fixed = FROM_DOCUMENTS[c.code];
              return (
                <tr key={c.id} className={c.is_active ? undefined : "rate-retired"}>
                  <td>
                    <TextInput value={c.name} disabled={!canEdit} onSave={(v) => save(c, { name: v }, "name")} />
                  </td>
                  <td className="rate-code">{c.code}</td>
                  <td>
                    <select
                      value={c.category}
                      disabled={!canEdit || c.code === "GSTD"}
                      onChange={(e) => save(c, { category: e.target.value as ChargeCategory }, "section")}
                    >
                      {(Object.keys(SECTIONS) as ChargeCategory[]).map((k) => (
                        <option key={k} value={k}>
                          {SECTIONS[k]}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <select
                      value={c.calculation_basis}
                      disabled={!canEdit || c.code === "GSTD"}
                      onChange={(e) =>
                        save(c, { calculation_basis: e.target.value as ChargeMasterEntry["calculation_basis"] }, "basis")
                      }
                    >
                      {(Object.keys(BASIS) as ChargeMasterEntry["calculation_basis"][]).map((k) => (
                        <option key={k} value={k}>
                          {BASIS[k]}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <TextInput
                      value={c.sac_code}
                      width={80}
                      disabled={!canEdit || c.code === "GSTD"}
                      pattern="\d{6}"
                      onSave={(v) => save(c, { sac_code: v }, "SAC")}
                    />
                  </td>
                  <td className="num">
                    <TextInput
                      value={String(Number(c.gst_rate))}
                      width={56}
                      numeric
                      disabled={!canEdit || c.code === "GSTD"}
                      onSave={(v) => save(c, { gst_rate: Number(v) }, "GST %")}
                    />
                  </td>
                  <td className="num">
                    {fixed ? (
                      <span className="field-note">{fixed}</span>
                    ) : (
                      <TextInput
                        value={c.default_rate == null ? "" : String(Number(c.default_rate))}
                        placeholder="—"
                        width={110}
                        numeric
                        allowEmpty
                        disabled={!canEdit}
                        onSave={(v) => save(c, { default_rate: v === "" ? null : Number(v) }, "standard rate")}
                      />
                    )}
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      role="switch"
                      checked={c.is_active}
                      disabled={!canEdit || c.code === "GSTD"}
                      title={c.is_active ? "Retire: hide from the proforma charge list" : "Bring back"}
                      onChange={() => save(c, { is_active: !c.is_active }, c.is_active ? "retired" : "active")}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      </>
      )}
      {tab === "numbering" && <InvoiceNumbering canEdit={canEdit} />}
      {tab === "licences" && <Licences charges={charges.filter((c) => c.is_active)} canEdit={canEdit} />}
      {tab === "hss" && <HssRules charges={charges.filter((c) => c.is_active)} canEdit={canEdit} />}
    </div>
  );
}

type Role = "seller" | "buyer";
type Pair = { key: string; buyer: string; seller: string; rules: Partial<Record<Role, PricingRule>>; lines: Record<Role, PricingRuleLine[]>; dirty: boolean };
const num = (v: unknown) => Number(v ?? 0) || 0;
const pairKey = (r: { importer_name: string; seller_name: string | null }) =>
  `${r.importer_name.trim().toUpperCase()}|${(r.seller_name ?? "").trim().toUpperCase()}`;

/**
 * HSS rules: for each seller → buyer pair (buyer = BE importer; seller blank = any
 * seller), the lines Fill puts on the seller copy and on the buyer copy.
 * amount = ₹/container × containers + ₹/kg × weight (kg) + flat.
 */
function HssRules({ charges, canEdit }: { charges: ChargeMasterEntry[]; canEdit: boolean }) {
  const confirm = useConfirm();
  const [pairs, setPairs] = useState<Pair[] | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [sample, setSample] = useState({ containers: "5", kg: "95800" });

  function load() {
    listPricingRules().then((rules) => {
      const map = new Map<string, Pair>();
      for (const r of rules) {
        const k = pairKey(r);
        const p = map.get(k) ?? { key: k, buyer: r.importer_name, seller: r.seller_name ?? "", rules: {}, lines: { seller: [], buyer: [] }, dirty: false };
        p.rules[r.bill_to_role] = r;
        p.lines[r.bill_to_role] = r.lines.map((l) => ({ ...l }));
        map.set(k, p);
      }
      setPairs([...map.values()]);
    });
  }
  useEffect(load, []);

  function change(i: number, f: (p: Pair) => Pair) {
    setPairs((prev) => prev?.map((p, j) => (j === i ? { ...f(p), dirty: true } : p)) ?? prev);
  }

  async function save(p: Pair) {
    if (!p.buyer.trim()) return setMsg({ kind: "error", text: "Enter the buyer (BE importer)." });
    try {
      for (const role of ["seller", "buyer"] as Role[]) {
        const lines = p.lines[role].filter((l) => l.code);
        const existing = p.rules[role];
        if (!lines.length && !existing) continue;
        await savePricingRule({
          id: existing?.id,
          name: `${p.seller.trim() || "Any seller"} → ${p.buyer.trim()} (${role} copy)`,
          importer_name: p.buyer.trim(),
          seller_name: p.seller.trim() || null,
          bill_to_role: role,
          lines,
          is_active: true,
        });
      }
      setMsg({ kind: "ok", text: `Saved HSS rule ${p.seller.trim() || "any seller"} → ${p.buyer.trim()}` });
      load();
    } catch (e) {
      setMsg({ kind: "error", text: errorText(e) });
    }
  }

  async function remove(p: Pair) {
    const ok = await confirm({
      title: "Delete HSS rule?",
      message: `Delete the rule ${p.seller || "any seller"} → ${p.buyer}? Proformas already filled keep their lines.`,
      confirmLabel: "Delete rule",
      danger: true,
    });
    if (!ok) return;
    for (const r of Object.values(p.rules)) if (r) await deletePricingRule(r.id);
    load();
  }

  const total = (lines: PricingRuleLine[]) =>
    lines.reduce((s, l) => {
      const c = charges.find((x) => x.code === l.code);
      const amount = num(l.per_container) * num(sample.containers) + num(l.per_kg) * num(sample.kg) + num(l.flat);
      return s + amount * (1 + num(c?.gst_rate) / 100);
    }, 0);

  if (!pairs) return null;
  return (
    <section className="hss-rules">
      <div className="rates-head">
        <div>
          <h2>HSS rules</h2>
          <p className="tracker-subtitle">
            For each seller → buyer pair: the lines "Fill / refresh" puts on the seller copy and on the buyer copy. Buyer
            = BE importer; leave the seller blank for any seller. Amount = ₹/container × containers + ₹/kg × weight + flat.
          </p>
        </div>
        <div className="rates-actions">
          <label className="hss-sample">
            Check with <input value={sample.containers} onChange={(e) => setSample({ ...sample, containers: e.target.value })} /> containers,{" "}
            <input value={sample.kg} onChange={(e) => setSample({ ...sample, kg: e.target.value })} /> kg
          </label>
          {canEdit && (
            <button
              onClick={() =>
                setPairs((prev) => [
                  ...(prev ?? []),
                  { key: `new-${Date.now()}`, buyer: "", seller: "", rules: {}, lines: { seller: [{ code: "ROY" }], buyer: [{ code: "ROY" }] }, dirty: true },
                ])
              }
            >
              + Add HSS rule
            </button>
          )}
        </div>
      </div>
      {msg && <div className={msg.kind === "ok" ? "grid-toast grid-toast-ok" : "grid-toast grid-toast-error"}>{msg.text}</div>}
      {pairs.length === 0 && <p className="tracker-subtitle">No HSS rules yet.</p>}
      {pairs.map((p, i) => {
        const st = total(p.lines.seller), bt = total(p.lines.buyer);
        return (
          <div className="hss-rule" key={p.key}>
            <div className="hss-rule-parties">
              <label>
                <span>Seller</span>
                <input value={p.seller} placeholder="any seller" disabled={!canEdit} onChange={(e) => change(i, (x) => ({ ...x, seller: e.target.value }))} />
              </label>
              <span className="hss-arrow">→</span>
              <label>
                <span>Buyer (BE importer)</span>
                <input value={p.buyer} placeholder="MAHRISHI RECYCLERS" disabled={!canEdit} onChange={(e) => change(i, (x) => ({ ...x, buyer: e.target.value }))} />
              </label>
              <span className={`hss-check ${Math.abs(st - bt) < 1 ? "ok" : "diff"}`}>
                Seller copy ₹{Math.round(st).toLocaleString("en-IN")} · Buyer copy ₹{Math.round(bt).toLocaleString("en-IN")} (incl. GST)
                {Math.abs(st - bt) < 1 ? " — same total" : " — totals differ"}
              </span>
            </div>
            <div className="hss-rule-copies">
              {(["seller", "buyer"] as Role[]).map((role) => (
                <div key={role} className="hss-copy">
                  <div className="hss-copy-title">{role === "seller" ? "Seller copy" : "Buyer copy"}</div>
                  <table>
                    <thead>
                      <tr>
                        <th>Charge</th>
                        <th className="num">₹ / container</th>
                        <th className="num">₹ / kg</th>
                        <th className="num">Flat ₹</th>
                        {canEdit && <th />}
                      </tr>
                    </thead>
                    <tbody>
                      {p.lines[role].map((l, j) => {
                        const set = (patch: Partial<PricingRuleLine>) =>
                          change(i, (x) => ({ ...x, lines: { ...x.lines, [role]: x.lines[role].map((y, k) => (k === j ? { ...y, ...patch } : y)) } }));
                        return (
                          <tr key={j}>
                            <td>
                              <select value={l.code} disabled={!canEdit} onChange={(e) => set({ code: e.target.value })}>
                                {charges.filter((c) => c.code !== "GSTD").map((c) => (
                                  <option key={c.code} value={c.code}>
                                    {c.name}
                                  </option>
                                ))}
                              </select>
                            </td>
                            {(["per_container", "per_kg", "flat"] as const).map((k) => (
                              <td key={k} className="num">
                                <input
                                  className="rate-input num"
                                  inputMode="decimal"
                                  value={l[k] == null ? "" : String(l[k])}
                                  placeholder="—"
                                  disabled={!canEdit}
                                  onChange={(e) => set({ [k]: e.target.value === "" ? null : e.target.value })}
                                />
                              </td>
                            ))}
                            {canEdit && (
                              <td>
                                <button type="button" className="link-danger link-button" onClick={() =>
                                  change(i, (x) => ({ ...x, lines: { ...x.lines, [role]: x.lines[role].filter((_, k) => k !== j) } }))}>
                                  ✕
                                </button>
                              </td>
                            )}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {canEdit && (
                    <button type="button" className="link-button" onClick={() =>
                      change(i, (x) => ({ ...x, lines: { ...x.lines, [role]: [...x.lines[role], { code: "OTHERCHARGES" }] } }))}>
                      + line
                    </button>
                  )}
                </div>
              ))}
            </div>
            {canEdit && (
              <div className="org-form-actions">
                <button disabled={!p.dirty} onClick={() => save(p)}>Save rule</button>
                {(p.rules.seller || p.rules.buyer) && (
                  <button className="btn-secondary link-danger" onClick={() => remove(p)}>Delete rule</button>
                )}
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}

/** Saves on Enter / leaving the box; Esc puts the old value back. */
function TextInput({
  value,
  onSave,
  disabled,
  numeric,
  allowEmpty,
  placeholder,
  pattern,
  width,
}: {
  value: string;
  onSave: (v: string) => void;
  disabled?: boolean;
  numeric?: boolean;
  allowEmpty?: boolean;
  placeholder?: string;
  pattern?: string;
  width?: number;
}) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  function commit() {
    const t = v.trim().replace(/,/g, "");
    if (t === value) return;
    const bad =
      (!allowEmpty && t === "") ||
      (numeric && t !== "" && (Number.isNaN(Number(t)) || Number(t) < 0)) ||
      (pattern && t !== "" && !new RegExp(`^${pattern}$`).test(t));
    if (bad) return setV(value);
    onSave(t);
  }
  return (
    <input
      className={`rate-input${numeric ? " num" : ""}`}
      style={width ? { width } : undefined}
      value={v}
      placeholder={placeholder}
      disabled={disabled}
      inputMode={numeric ? "decimal" : undefined}
      onChange={(e) => setV(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        if (e.key === "Escape") setV(value);
      }}
    />
  );
}

function NewCharge({ onCreated, onError }: { onCreated: (c: ChargeMasterEntry) => void; onError: (t: string) => void }) {
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [category, setCategory] = useState<ChargeCategory>("service");
  const [basis, setBasis] = useState<ChargeMasterEntry["calculation_basis"]>("flat");
  const [sac, setSac] = useState("996713");
  const [gst, setGst] = useState("18");
  const [rate, setRate] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      onCreated(
        await createCharge({
          name: name.trim(),
          code: code.trim().toUpperCase(),
          category,
          calculation_basis: basis,
          sac_code: sac.trim(),
          gst_rate: Number(gst),
          default_rate: rate.trim() === "" ? null : Number(rate),
        }),
      );
    } catch (err) {
      onError(errorText(err));
    }
  }

  return (
    <form className="org-form" onSubmit={submit}>
      <label className="wide">
        <span>Charge name *</span>
        <input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Other Fees" />
      </label>
      <label>
        <span>Code * (A–Z, 0–9)</span>
        <input required pattern="[A-Za-z0-9_]+" value={code} onChange={(e) => setCode(e.target.value)} placeholder="OTHERFEES" />
      </label>
      <label>
        <span>Section</span>
        <select value={category} onChange={(e) => setCategory(e.target.value as ChargeCategory)}>
          {(Object.keys(SECTIONS) as ChargeCategory[]).map((k) => (
            <option key={k} value={k}>
              {SECTIONS[k]}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Basis</span>
        <select value={basis} onChange={(e) => setBasis(e.target.value as ChargeMasterEntry["calculation_basis"])}>
          {(Object.keys(BASIS) as ChargeMasterEntry["calculation_basis"][]).map((k) => (
            <option key={k} value={k}>
              {BASIS[k]}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>SAC</span>
        <input pattern="\d{6}" value={sac} onChange={(e) => setSac(e.target.value)} />
      </label>
      <label>
        <span>GST %</span>
        <input inputMode="decimal" value={gst} onChange={(e) => setGst(e.target.value)} />
      </label>
      <label>
        <span>Standard rate (₹)</span>
        <input inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} placeholder="optional" />
      </label>
      <div className="org-form-actions wide">
        <button type="submit">Add charge</button>
      </div>
    </form>
  );
}

/**
 * Licence rates: the charges pre-filled on a new proforma for shipments under
 * the licence. Seller / port narrow a row (most specific wins); on HSS
 * shipments the seller is the HSS seller. A closed licence falls back to the
 * standard rates.
 */
function Licences({ charges, canEdit }: { charges: ChargeMasterEntry[]; canEdit: boolean }) {
  const ports = usePorts();
  const [items, setItems] = useState<(Licence & { dirty?: boolean })[] | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [open, setOpen] = useState<Set<number>>(new Set()); // licences shown as rows; click to open
  const toggleOpen = (id: number) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const load = () => listLicences().then(setItems);
  useEffect(() => {
    load();
  }, []);

  function change(i: number, patch: Partial<Licence>) {
    setItems((prev) => prev?.map((l, j) => (j === i ? { ...l, ...patch, dirty: true } : l)) ?? prev);
  }
  function setRow(i: number, j: number, patch: Partial<LicenceRate>) {
    setItems((prev) =>
      prev?.map((l, k) => (k === i ? { ...l, dirty: true, rates: l.rates.map((r, m) => (m === j ? { ...r, ...patch } : r)) } : l)) ?? prev,
    );
  }
  async function save(l: Licence & { dirty?: boolean }) {
    try {
      const { dirty: _d, ...body } = l;
      void _d;
      await saveLicence({ ...body, id: l.id > 0 ? l.id : undefined, rates: l.rates.filter((r) => r.code) });
      setMsg({ kind: "ok", text: `Saved licence ${l.number}` });
      load();
    } catch (e) {
      setMsg({ kind: "error", text: errorText(e) });
    }
  }

  if (!items) return null;
  const chargeName = (code: string) => charges.find((c) => c.code === code)?.name ?? code;
  return (
    <section className="hss-rules">
      <div className="rates-head">
        <div>
          <h2>Licences</h2>
          <p className="tracker-subtitle">
            Charges filled in on every new proforma for shipments under the licence (the licence belongs to the BE importer).
            Leave seller / port blank for "any"; the most specific row wins. Examination is added only while the shipment is
            under examination.
          </p>
        </div>
        {canEdit && (
          <div className="rates-actions">
            <button
              onClick={() => {
                const id = -Date.now();
                setItems((prev) => [...(prev ?? []), { id, number: "", importer_name: "", rates: [{ code: "AC", per_container: 7000 }], is_active: true, notes: null, dirty: true }]);
                setOpen((prev) => new Set(prev).add(id));
              }}
            >
              + Add licence
            </button>
          </div>
        )}
      </div>
      {msg && <div className={msg.kind === "ok" ? "grid-toast grid-toast-ok" : "grid-toast grid-toast-error"}>{msg.text}</div>}
      <div className="licence-list">
      {items.map((l, i) => (
        <div className={`licence-item${l.is_active ? "" : " licence-closed"}${open.has(l.id) ? " is-open" : ""}`} key={l.id}>
          <button type="button" className="licence-summary" aria-expanded={open.has(l.id)} onClick={() => toggleOpen(l.id)}>
            <span className="licence-caret">{open.has(l.id) ? "▾" : "▸"}</span>
            <span className="licence-no">{l.number || "New licence"}</span>
            <span className="licence-importer">{l.importer_name || "—"}</span>
            <span className="licence-count">
              {l.rates.length} rate{l.rates.length === 1 ? "" : "s"}
            </span>
            <span className={`status-pill ${l.is_active ? "status-cleared" : ""}`}>{l.is_active ? "Active" : "Closed"}</span>
            {l.dirty && <span className="edited-tag">unsaved</span>}
          </button>
          {open.has(l.id) && (
          <div className="licence-body">
          <div className="hss-rule-parties">
            <label>
              <span>Licence no.</span>
              <input value={l.number} disabled={!canEdit || l.id > 0} onChange={(e) => change(i, { number: e.target.value })} />
            </label>
            <label>
              <span>BE importer</span>
              <input value={l.importer_name ?? ""} disabled={!canEdit} onChange={(e) => change(i, { importer_name: e.target.value })} />
            </label>
            <label className="toggle-row">
              <span>{l.is_active ? "Active" : "Closed"}</span>
              <input type="checkbox" role="switch" checked={l.is_active} disabled={!canEdit} onChange={() => change(i, { is_active: !l.is_active })} />
            </label>
            {l.notes && <span className="field-note">{l.notes}</span>}
          </div>
          <div className="hss-copy">
            <table>
              <thead>
                <tr>
                  <th>Charge</th>
                  <th>Seller (HSS)</th>
                  <th>Port</th>
                  <th className="num">₹ / container</th>
                  <th className="num">₹ / kg</th>
                  <th className="num">Flat ₹</th>
                  {canEdit && <th />}
                </tr>
              </thead>
              <tbody>
                {l.rates.map((r, j) => (
                  <tr key={j}>
                    <td>
                      <select value={r.code} disabled={!canEdit} onChange={(e) => setRow(i, j, { code: e.target.value })} title={chargeName(r.code)}>
                        {charges.filter((c) => !["GSTD", "CD", "SD", "CFS", "DO"].includes(c.code)).map((c) => (
                          <option key={c.code} value={c.code}>
                            {c.name}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <input className="rate-input" value={r.seller ?? ""} placeholder="any" disabled={!canEdit} onChange={(e) => setRow(i, j, { seller: e.target.value || null })} />
                    </td>
                    <td>
                      <select value={r.port ?? ""} disabled={!canEdit} onChange={(e) => setRow(i, j, { port: e.target.value || null })}>
                        <option value="">any</option>
                        {ports.map((p) => (
                          <option key={p.code} value={p.code}>
                            {p.code} · {p.name}
                          </option>
                        ))}
                      </select>
                    </td>
                    {(["per_container", "per_kg", "flat"] as const).map((k) => (
                      <td key={k} className="num">
                        <input
                          className="rate-input num"
                          inputMode="decimal"
                          value={r[k] == null ? "" : String(r[k])}
                          placeholder="—"
                          disabled={!canEdit}
                          onChange={(e) => setRow(i, j, { [k]: e.target.value === "" ? null : e.target.value })}
                        />
                      </td>
                    ))}
                    {canEdit && (
                      <td>
                        <button type="button" className="link-danger link-button" onClick={() => change(i, { rates: l.rates.filter((_, m) => m !== j) })}>
                          ✕
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            {canEdit && (
              <button type="button" className="link-button" onClick={() => change(i, { rates: [...l.rates, { code: "SBOND" }] })}>
                + rate
              </button>
            )}
          </div>
          {canEdit && (
            <div className="org-form-actions">
              <button disabled={!l.dirty || !l.number.trim()} onClick={() => save(l)}>
                Save licence
              </button>
            </div>
          )}
          </div>
          )}
        </div>
      ))}
      </div>
    </section>
  );
}

/** Where the final-invoice series continues (CL/<n>/<FY>, RI/CL/<n>/<FY>). */
function InvoiceNumbering({ canEdit }: { canEdit: boolean }) {
  const [rows, setRows] = useState<{ fy: string; next_seq: number }[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    getInvoiceCounters().then((r) => setRows(r.counters));
  }, []);
  return (
    <section className="hss-rules">
      <h2>Invoice numbering</h2>
      <p className="tracker-subtitle">
        Next final-invoice number per financial year — Tax Invoice CL/&lt;n&gt;/&lt;FY&gt;, Reimbursement RI/CL/&lt;n&gt;/&lt;FY&gt;
        (a pair from one proforma shares &lt;n&gt;). Set it to continue from the last invoice made elsewhere.
      </p>
      <div className="numbering-rows">
        {rows.map((r) => (
          <label key={r.fy} className="final-field numbering-row">
            <span>FY {r.fy} — next number</span>
            <TextInput
              value={String(r.next_seq)}
              numeric
              width={100}
              disabled={!canEdit}
              onSave={(v) =>
                setInvoiceCounter(r.fy, Number(v))
                  .then((c) => {
                    setRows((prev) => prev.map((x) => (x.fy === c.fy ? c : x)));
                    setMsg(`Next invoice for FY ${c.fy}: CL/${c.next_seq}/${c.fy}`);
                  })
                  .catch((e) => setMsg(errorText(e)))
              }
            />
          </label>
        ))}
      </div>
      {msg && <div className="field-note">{msg}</div>}
    </section>
  );
}
