import { useState, type FormEvent } from "react";
import type { ColumnDataType, TrackerColumn } from "./types";

export interface PanelColumn {
  colId: string;
  label: string;
  visible: boolean;
  isCustom: boolean;
  removable: boolean;
}

interface Props {
  columns: PanelColumn[];
  removed: TrackerColumn[];
  isAdmin: boolean;
  onToggle: (colId: string, visible: boolean) => void;
  onShowAll: () => void;
  onAdd: (label: string, type: ColumnDataType) => Promise<void>;
  onDelete: (col: PanelColumn) => Promise<void>;
  onRestore: (key: string) => Promise<void>;
  onClose: () => void;
}

const TYPE_LABELS: Record<ColumnDataType, string> = {
  text: "Text",
  date: "Date",
  number: "Number",
  boolean: "Yes / No",
};

/**
 * Show/hide is personal (saved in your layout). Add / delete / restore change
 * the tracker for everyone, so they're admin-only.
 */
export default function ColumnsPanel(props: Props) {
  const { columns, removed, isAdmin } = props;
  const [label, setLabel] = useState("");
  const [type, setType] = useState<ColumnDataType>("text");
  const [busy, setBusy] = useState(false);

  async function add(e: FormEvent) {
    e.preventDefault();
    if (!label.trim()) return;
    setBusy(true);
    try {
      await props.onAdd(label.trim(), type);
      setLabel("");
      setType("text");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="columns-panel" role="dialog" aria-label="Columns">
      <div className="columns-panel-head">
        <strong>Columns</strong>
        <div>
          <button type="button" className="link-btn" onClick={props.onShowAll}>
            Show all
          </button>
          <button type="button" className="link-btn" onClick={props.onClose} aria-label="Close">
            ✕
          </button>
        </div>
      </div>
      <p className="columns-panel-hint">Untick to hide a column for you only.</p>

      <ul className="columns-list">
        {columns.map((c) => (
          <li key={c.colId}>
            <label>
              <input type="checkbox" checked={c.visible} onChange={(e) => props.onToggle(c.colId, e.target.checked)} />
              {c.label}
              {c.isCustom && <span className="columns-tag">custom</span>}
            </label>
            {isAdmin && c.removable && (
              <button
                type="button"
                className="columns-delete"
                title={c.isCustom ? "Delete column and its data" : "Remove for everyone (data kept, can restore)"}
                onClick={() => props.onDelete(c)}
              >
                Delete
              </button>
            )}
          </li>
        ))}
      </ul>

      {isAdmin && (
        <form className="columns-add" onSubmit={add}>
          <strong>Add a column</strong>
          <input placeholder="Column name" value={label} onChange={(e) => setLabel(e.target.value)} maxLength={60} />
          <select value={type} onChange={(e) => setType(e.target.value as ColumnDataType)}>
            {(Object.keys(TYPE_LABELS) as ColumnDataType[]).map((t) => (
              <option key={t} value={t}>
                {TYPE_LABELS[t]}
              </option>
            ))}
          </select>
          <button type="submit" disabled={busy || !label.trim()}>
            {busy ? "Adding…" : "Add"}
          </button>
        </form>
      )}

      {isAdmin && removed.length > 0 && (
        <div className="columns-removed">
          <strong>Removed columns</strong>
          <ul className="columns-list">
            {removed.map((c) => (
              <li key={c.key}>
                <span>{c.label}</span>
                <button type="button" className="link-btn" onClick={() => props.onRestore(c.key)}>
                  Restore
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
