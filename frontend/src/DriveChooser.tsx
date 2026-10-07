import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { listDriveFolderPdfs, searchServerDriveFolders, type DriveFolderHit } from "./api";

/**
 * In-ERP Drive chooser: folders and PDFs are found by the server's own Drive connection,
 * so nobody signs in to Google or uses Google's picker. Read only.
 *   mode "folder": search and pick a folder
 *   mode "file" / "files": pick one / several PDFs from a folder (search another if needed)
 */
type Mode = "folder" | "file" | "files";
type Picked = { id: string; name: string };
export type ChooserResult = { folder: DriveFolderHit } | { files: Picked[] } | null;

function errText(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : fallback;
}

function DriveChooser({
  mode,
  folderId,
  onDone,
}: {
  mode: Mode;
  folderId?: string | null;
  onDone: (r: ChooserResult) => void;
}) {
  const [folder, setFolder] = useState<{ id: string; name: string } | null>(
    mode !== "folder" && folderId ? { id: folderId, name: "This shipment's folder" } : null,
  );
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<DriveFolderHit[] | null>(null);
  const [pdfs, setPdfs] = useState<Picked[] | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const searchBox = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onDone(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onDone]);

  useEffect(() => {
    if (!folder || mode === "folder") {
      searchBox.current?.focus();
      return;
    }
    let live = true;
    setBusy(true);
    setError(null);
    setPdfs(null);
    setChosen(new Set());
    listDriveFolderPdfs(folder.id)
      .then((r) => live && setPdfs(r))
      .catch((e) => live && setError(errText(e, "Couldn't open that folder.")))
      .finally(() => live && setBusy(false));
    return () => {
      live = false;
    };
  }, [folder, mode]);

  async function search(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (q.length < 3) return setError("Type at least 3 letters — e.g. the BL no or “JOB 129”.");
    setBusy(true);
    setError(null);
    try {
      setHits(await searchServerDriveFolders([q]));
    } catch (err) {
      setError(errText(err, "Couldn't search Google Drive."));
    } finally {
      setBusy(false);
    }
  }

  function pickFolder(f: DriveFolderHit) {
    if (mode === "folder") onDone({ folder: f });
    else setFolder({ id: f.id, name: f.name });
  }

  const browsing = mode !== "folder" && folder;
  const title =
    mode === "folder" ? "Choose this shipment's folder" : mode === "file" ? "Choose the PDF" : "Select the shipment's files";

  return (
    <div className="confirm-backdrop" onMouseDown={() => onDone(null)}>
      <div
        ref={dialog}
        className="confirm-dialog drive-chooser"
        role="dialog"
        aria-modal="true"
        aria-labelledby="drive-chooser-title"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2 id="drive-chooser-title">{title}</h2>
        {browsing ? (
          <>
            <p className="field-note">
              In <strong>{folder.name}</strong>{" "}
              <button type="button" className="link-btn" onClick={() => setFolder(null)}>
                Other folder…
              </button>
            </p>
            {busy && <p className="field-note">Reading the folder…</p>}
            {pdfs && !pdfs.length && <p className="field-note">No PDFs in this folder.</p>}
            {pdfs && pdfs.length > 0 && (
              <ul className="drive-chooser-list">
                {pdfs.map((f) => (
                  <li key={f.id}>
                    {mode === "file" ? (
                      <button type="button" className="link-btn" onClick={() => onDone({ files: [f] })}>
                        {f.name}
                      </button>
                    ) : (
                      <label>
                        <input
                          type="checkbox"
                          checked={chosen.has(f.id)}
                          onChange={(e) => {
                            const next = new Set(chosen);
                            if (e.target.checked) next.add(f.id);
                            else next.delete(f.id);
                            setChosen(next);
                          }}
                        />{" "}
                        {f.name}
                      </label>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </>
        ) : (
          <>
            <form onSubmit={search} className="drive-chooser-search">
              <input
                ref={searchBox}
                placeholder="Folder name — BL no, job no…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="Folder name"
              />
              <button type="submit" disabled={busy}>
                {busy ? "Searching…" : "Search"}
              </button>
            </form>
            {hits && !hits.length && <p className="field-note">No folder with that in its name.</p>}
            {hits && hits.length > 0 && (
              <ul className="drive-chooser-list">
                {hits.map((f) => (
                  <li key={f.id}>
                    <button type="button" className="link-btn" onClick={() => pickFolder(f)}>
                      {f.name}
                    </button>{" "}
                    <a href={f.url} target="_blank" rel="noreferrer" aria-label={`Open ${f.name} in Drive`}>
                      ↗
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
        {error && (
          <p className="auth-error" role="alert">
            {error}
          </p>
        )}
        <div className="confirm-actions">
          <button type="button" className="btn-secondary" onClick={() => onDone(null)}>
            Cancel
          </button>
          {mode === "files" && browsing && (
            <button
              type="button"
              disabled={!chosen.size}
              onClick={() => onDone({ files: (pdfs ?? []).filter((f) => chosen.has(f.id)) })}
            >
              Add {chosen.size || ""} selected
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/** Opens the chooser and resolves with what was picked (null if cancelled). */
export function openDriveChooser(mode: Mode, folderId?: string | null): Promise<ChooserResult> {
  const opener = document.activeElement as HTMLElement | null;
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  return new Promise((resolve) => {
    const done = (r: ChooserResult) => {
      root.unmount();
      host.remove();
      opener?.focus?.();
      resolve(r);
    };
    root.render(<DriveChooser mode={mode} folderId={folderId} onDone={done} />);
  });
}
