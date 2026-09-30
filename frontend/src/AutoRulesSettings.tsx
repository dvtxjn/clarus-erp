import { useEffect, useState } from "react";
import { getAutoRules, saveAutoRules, type AutoRules, type CustomRule } from "./api";

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Something went wrong — try again.";
}

const blank = (): CustomRule => ({ source: "mail", kind: "", contains: "", field: null, attention: true, enabled: true });

/**
 * Settings → Automatic rules (client, 2026-09-30): what the ERP does by itself when an ICEGATE / ODeX mail
 * or an ICEGATE BE status arrives, as IF … THEN … lines. The admin switches built-in rules on / off and adds
 * simple rules of their own (tick a box and/or flag Needs attention). Old mails never change anything.
 */
export default function AutoRulesSettings() {
  const [r, setR] = useState<AutoRules | null>(null);
  const [off, setOff] = useState<Set<string>>(new Set());
  const [custom, setCustom] = useState<CustomRule[]>([]);
  const [days, setDays] = useState("45");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  function take(x: AutoRules) {
    setR(x);
    setOff(new Set(x.builtin.filter((b) => !b.enabled).map((b) => b.id)));
    setCustom(x.custom);
    setDays(String(x.history_days));
    setDirty(false);
  }
  useEffect(() => {
    getAutoRules().then(take).catch(() => setR(null));
  }, []);

  const change = (fn: () => void) => {
    fn();
    setDirty(true);
    setMsg(null);
  };
  const setRule = (i: number, patch: Partial<CustomRule>) =>
    change(() => setCustom((c) => c.map((x, j) => (j === i ? { ...x, ...patch } : x))));

  async function save() {
    setBusy(true);
    try {
      take(await saveAutoRules({ off: [...off], custom, history_days: Number(days) || 45 }));
      setMsg({ ok: true, text: "Rules saved — they apply to the next mail or ICEGATE check." });
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    } finally {
      setBusy(false);
    }
  }

  if (!r) return <p className="field-note">Loading rules…</p>;
  return (
    <div className="rules">
      <table className="tracker-grid rules-table">
        <thead>
          <tr>
            <th>On</th>
            <th>If</th>
            <th>Then</th>
          </tr>
        </thead>
        <tbody>
          {r.builtin.map((b) => (
            <tr key={b.id} className={off.has(b.id) ? "is-off" : undefined}>
              <td>
                <input
                  type="checkbox"
                  aria-label={`${b.when}: on`}
                  checked={!off.has(b.id)}
                  onChange={(e) =>
                    change(() =>
                      setOff((o) => {
                        const n = new Set(o);
                        if (e.target.checked) n.delete(b.id);
                        else n.add(b.id);
                        return n;
                      }),
                    )
                  }
                />
              </td>
              <td>{b.when}</td>
              <td>{b.then}</td>
            </tr>
          ))}
          <tr>
            <td />
            <td>A mail is older than</td>
            <td>
              <input
                type="number"
                min={1}
                max={3650}
                inputMode="numeric"
                aria-label="Old-mail limit in days"
                value={days}
                onChange={(e) => change(() => setDays(e.target.value))}
                style={{ width: 70 }}
              />{" "}
              days → timeline only, nothing changed (the same for archived or billed jobs)
            </td>
          </tr>
        </tbody>
      </table>

      <h3 className="rules-sub">Your own rules</h3>
      {custom.length === 0 && <p className="field-note">None yet. A rule can tick a box and/or flag Needs attention — it never unticks or overwrites.</p>}
      {custom.map((c, i) => (
        <div key={c.id ?? `new-${i}`} className={`rule-row${c.enabled ? "" : " is-off"}`}>
          <input type="checkbox" aria-label="Rule on" checked={c.enabled} onChange={(e) => setRule(i, { enabled: e.target.checked })} />
          <span>If</span>
          <select
            aria-label="Rule starts from"
            value={c.source}
            onChange={(e) => setRule(i, { source: e.target.value as CustomRule["source"], kind: "", queue: "" })}
          >
            <option value="mail">a mail of type</option>
            <option value="be_queue">ICEGATE BE status queue is</option>
          </select>
          {c.source === "mail" ? (
            <>
              <select aria-label="Mail type" value={c.kind ?? ""} onChange={(e) => setRule(i, { kind: e.target.value })}>
                <option value="">Pick a type…</option>
                {r.kinds.map((k) => (
                  <option key={k.kind} value={k.kind}>
                    {k.label}
                  </option>
                ))}
              </select>
              <input
                aria-label="Only when the text contains"
                placeholder="containing… (optional)"
                value={c.contains ?? ""}
                onChange={(e) => setRule(i, { contains: e.target.value })}
                spellCheck={false}
              />
            </>
          ) : (
            <input
              aria-label="Queue code"
              placeholder="e.g. APR…"
              value={c.queue ?? ""}
              onChange={(e) => setRule(i, { queue: e.target.value.toUpperCase() })}
              spellCheck={false}
              style={{ width: 90 }}
            />
          )}
          <span>then</span>
          <select aria-label="Tick" value={c.field ?? ""} onChange={(e) => setRule(i, { field: e.target.value || null })}>
            <option value="">tick nothing</option>
            {r.fields.map((f) => (
              <option key={f.field} value={f.field}>
                tick {f.label}
              </option>
            ))}
          </select>
          <label className="rule-attn">
            <input type="checkbox" checked={c.attention} onChange={(e) => setRule(i, { attention: e.target.checked })} />
            Needs attention
          </label>
          <button type="button" className="link-button link-danger" aria-label="Remove rule" onClick={() => change(() => setCustom((x) => x.filter((_, j) => j !== i)))}>
            Remove
          </button>
        </div>
      ))}
      <div className="settings-save">
        <button type="button" className="btn-secondary" onClick={() => change(() => setCustom((x) => [...x, blank()]))}>
          + Add a rule
        </button>
        <button type="button" disabled={!dirty || busy} onClick={save}>
          {busy ? "Saving…" : "Save rules"}
        </button>
        {dirty && (
          <button type="button" className="btn-secondary" disabled={busy} onClick={() => take(r)}>
            Undo changes
          </button>
        )}
        {msg && (
          <span role="status" aria-live="polite" className={msg.ok ? "settings-ok" : "auth-error"}>
            {msg.text}
          </span>
        )}
      </div>
    </div>
  );
}
