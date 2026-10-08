import { useEffect, useRef, useState } from "react";
import { getFolderFiles, markFolderFile, syncFolder, type FolderFile, type FolderFileStatus } from "./api";
import { DOCUMENT_GROUPS, DOCUMENT_TYPE_LABELS, docShort, LEGACY_DOCUMENT_TYPES, type DocumentType, type Shipment } from "./types";

const STATUS: Record<FolderFileStatus, [string, string]> = {
  added: ["Attached now", "ok"],
  attached: ["Attached", "ok"],
  not_attached: ["Not attached", "warn"],
  ignored: ["Ignored", "muted"],
  unrecognised: ["Not recognised — mark it", "warn"],
  duplicate: ["Not attached — one is already attached; mark it to add this too", "muted"],
  removed: ["Removed from the shipment — mark it to attach again", "muted"],
  error: ["Couldn't read", "bad"],
};

const FILTERS: [string, string, (f: FolderFile) => boolean][] = [
  ["needs", "Needs a look", (f) => ["not_attached", "unrecognised", "duplicate", "error"].includes(f.status)],
  ["attached", "Attached", (f) => f.status === "added" || f.status === "attached"],
  ["ignored", "Ignored / removed", (f) => f.status === "ignored" || f.status === "removed"],
  ["all", "All files", () => true],
];

const TYPES = (Object.keys(DOCUMENT_TYPE_LABELS) as DocumentType[]).filter((t) => !LEGACY_DOCUMENT_TYPES.includes(t));
const label = (t: string | null) => (t ? (t in DOCUMENT_TYPE_LABELS ? docShort(t as DocumentType) : t) : "");
/** Drive can hang: after 10s say so and offer Retry instead of "Reading…" forever (the read may still finish). */
const READ_TIMEOUT_MS = 10_000;
function within<T>(p: Promise<T>): Promise<T> {
  return Promise.race([p, new Promise<T>((_, no) => window.setTimeout(() => no(new Error("timeout")), READ_TIMEOUT_MS))]);
}
const errText = (e: unknown, fallback: string) => {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : fallback;
};

// read once per shipment per browser tab on opening (kept across reloads); again whenever the folder link changes
const SEEN_KEY = "folderReader.read";
const readThisSession = new Set<string>(
  (() => {
    try {
      return JSON.parse(sessionStorage.getItem(SEEN_KEY) || "[]") as string[];
    } catch {
      return [];
    }
  })(),
);
function markRead(key: string) {
  readThisSession.add(key);
  try {
    sessionStorage.setItem(SEEN_KEY, JSON.stringify([...readThisSession]));
  } catch {
    /* private mode: only this page load remembers */
  }
}

/**
 * Folder reader (client, 2026-10-05): every PDF in the shipment's linked Drive folder is
 * recognised, attached and read (details fill in, like an upload). Each file can be marked
 * as any document, ignored, or handed back to the reader ("Auto"); marks are kept and every
 * re-read respects them. Drive itself is only read — nothing there is moved or changed.
 */
export function FolderReader({ shipment, onChanged }: { shipment: Shipment; onChanged: () => void }) {
  const [files, setFiles] = useState<FolderFile[] | null>(null);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<string | null>(null);
  const [filter, setFilter] = useState("needs");
  const [open, setOpen] = useState(true);
  const folderId = shipment.drive_folder_id;
  const busy = useRef(false);

  async function read() {
    if (busy.current) return;
    busy.current = true;
    setReading(true);
    setError(null);
    try {
      const r = await within(syncFolder(shipment.id));
      setFiles(r.files);
      const added = r.files.filter((f) => f.status === "added").length;
      setSummary(
        [
          added ? `${added} document${added === 1 ? "" : "s"} attached` : "Nothing new to attach",
          r.updated.length ? `updated: ${r.updated.join(", ")}` : "",
        ]
          .filter(Boolean)
          .join(" · "),
      );
      if (added || r.updated.length) onChanged();
    } catch (e) {
      setError(errText(e, "Couldn't read the Drive folder."));
    } finally {
      busy.current = false;
      setReading(false);
    }
  }

  useEffect(() => {
    if (!folderId) return;
    const key = `${shipment.id}:${folderId}`;
    if (readThisSession.has(key)) {
      within(getFolderFiles(shipment.id)).then(setFiles, (e) => setError(errText(e, "Couldn't read the Drive folder.")));
    } else {
      markRead(key);
      read();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shipment.id, folderId]);

  async function mark(f: FolderFile, value: string) {
    setError(null);
    try {
      await markFolderFile(shipment.id, f.file_id, value === "auto" ? null : value, f.name);
      await read();
    } catch (e) {
      setError(errText(e, "Couldn't save the mark."));
    }
  }

  if (!folderId) return null;
  const pick = FILTERS.find(([id]) => id === filter)!;
  const shown = (files ?? []).filter(pick[2]);
  const needs = (files ?? []).filter(FILTERS[0][2]).length;

  return (
    <section className="folder-reader tracker-grid-wrap">
      <div className="doc-group-head">
        <button type="button" className="link-btn" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? "▾" : "▸"} Files in the Drive folder
        </button>
        <span className="doc-group-count">
          {files ? `${files.length} PDF${files.length === 1 ? "" : "s"}${needs ? ` · ${needs} need a look` : ""}` : ""}
        </span>
        <button type="button" className="btn-secondary" onClick={read} disabled={reading}>
          {reading ? "Reading folder…" : "Read folder again"}
        </button>
      </div>
      {open && (
        <>
          {summary && <p className="tracker-subtitle">{summary}</p>}
          {error && (
            <div className="auth-error" role="alert">
              {error}{" "}
              <button type="button" className="link-btn" onClick={read} disabled={reading}>
                Retry
              </button>
            </div>
          )}
          <div className="folder-reader-filters">
            {FILTERS.map(([id, text]) => (
              <label key={id}>
                <input type="radio" name={`fr-${shipment.id}`} checked={filter === id} onChange={() => setFilter(id)} />{" "}
                {text}
              </label>
            ))}
          </div>
          {files === null ? (
            <div className="tracker-empty">
              {reading ? "Reading the folder…" : error ? "The folder's files show here once it has been read." : "Loading…"}
            </div>
          ) : shown.length === 0 ? (
            <div className="tracker-empty">
              {files.length === 0 ? "No PDFs in this folder." : "Nothing here — try another filter."}
            </div>
          ) : (
            <table className="rates-table folder-reader-table">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Status</th>
                  <th>Marked as</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((f) => {
                  const [text, tone] = STATUS[f.status];
                  return (
                    <tr key={f.file_id}>
                      <td className="assign-name">
                        <a href={f.link} target="_blank" rel="noreferrer">
                          {f.name}
                        </a>
                      </td>
                      <td>
                        <span className={`folder-status folder-status-${tone}`} title={f.error}>
                          {text}
                          {f.document_type && (f.status === "added" || f.status === "attached")
                            ? ` as ${label(f.document_type)}`
                            : ""}
                        </span>
                      </td>
                      <td>
                        <select value={f.mark ?? "auto"} onChange={(e) => mark(f, e.target.value)} disabled={reading}>
                          <option value="auto">Auto{f.guess ? ` (${label(f.guess)})` : " (not recognised)"}</option>
                          <option value="ignore">Ignore this file</option>
                          {DOCUMENT_GROUPS.map((g) => (
                            <optgroup key={g.id} label={g.label}>
                              {g.types.filter((t) => TYPES.includes(t)).map((t) => (
                                <option key={t} value={t}>
                                  {DOCUMENT_TYPE_LABELS[t]}
                                </option>
                              ))}
                            </optgroup>
                          ))}
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          <p className="field-note">
            The folder is only read — nothing in Drive is moved, renamed or deleted. Marks are kept: every re-read follows
            them. "Ignore" on an attached file takes it off the shipment (admin only).
          </p>
        </>
      )}
    </section>
  );
}
