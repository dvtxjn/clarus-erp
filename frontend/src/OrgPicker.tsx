import { useEffect, useId, useRef, useState } from "react";
import type { CustomCellEditorProps } from "ag-grid-react";
import { getShipmentNames } from "./api";

/**
 * The central client list (Settings → Organizations) for every seller / buyer / client field
 * (client, 2026-10-09). Loaded once per page load and shared; refreshed after a minute so a client
 * added meanwhile shows up.
 */
let cache: { at: number; names: Promise<string[]> } | null = null;

export function useOrgNames(): string[] {
  const [names, setNames] = useState<string[]>([]);
  useEffect(() => {
    if (!cache || Date.now() - cache.at > 60_000) {
      cache = { at: Date.now(), names: getShipmentNames().then((r) => r.organizations ?? []).catch(() => []) };
    }
    let live = true;
    cache.names.then((n) => live && setNames(n));
    return () => {
      live = false;
    };
  }, []);
  return names;
}

/**
 * Type-to-search over the client list. A name matching one in the list except for capitals takes
 * the list's spelling; anything else is kept as typed and flagged "not in Organizations".
 */
export function OrgPicker(props: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  extra?: string[]; // other names offered too (e.g. ones used before)
}) {
  const id = useId();
  const orgs = useOrgNames();
  const options = props.extra ? [...new Set([...orgs, ...props.extra])] : orgs;
  const typed = props.value.trim();
  const known = options.find((o) => o.toUpperCase() === typed.toUpperCase());
  const inOrgs = orgs.some((o) => o.toUpperCase() === typed.toUpperCase());
  return (
    <span className="pick-or-add">
      <input
        list={id}
        className={props.className}
        aria-label={props.label}
        placeholder={props.placeholder ?? `${props.label} — type to search…`}
        autoComplete="off"
        spellCheck={false}
        disabled={props.disabled}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        onBlur={() => known && known !== props.value && props.onChange(known)}
      />
      <datalist id={id}>
        {options.map((o) => (
          <option key={o} value={o} />
        ))}
      </datalist>
      {typed && orgs.length > 0 && !inOrgs && !props.disabled && <span className="field-note">not in Organizations</span>}
    </span>
  );
}

/** Tracker grid cells (Client / Consignee): the same type-to-search over the client list. */
export function OrgCellEditor(props: CustomCellEditorProps<unknown, string | null>) {
  const id = useId();
  const orgs = useOrgNames();
  const [text, setText] = useState(() =>
    props.eventKey && props.eventKey.length === 1 ? props.eventKey : String(props.initialValue ?? ""),
  );
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => ref.current?.focus(), []);
  const set = (v: string) => {
    setText(v);
    const known = orgs.find((o) => o.toUpperCase() === v.trim().toUpperCase());
    props.onValueChange((known ?? v).trim() || null);
  };
  return (
    <>
      <input
        ref={ref}
        list={id}
        className="ag-input-field-input ag-text-field-input"
        style={{ width: "100%", height: "100%" }}
        aria-label="Client list"
        autoComplete="off"
        spellCheck={false}
        value={text}
        onChange={(e) => set(e.target.value)}
      />
      <datalist id={id}>
        {orgs.map((o) => (
          <option key={o} value={o} />
        ))}
      </datalist>
    </>
  );
}
