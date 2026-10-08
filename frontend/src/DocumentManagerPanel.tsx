import { fmtWhen, fmtWhenDay } from "./dates";
import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  addDocumentFromDrive,
  getDocumentChecklist,
  openDocumentFile,
  removeDocument,
  rereadDocument,
  uploadDocument,
} from "./api";
import { useSaveShipment } from "./useSaveShipment";
import { useAuth } from "./AuthContext";
import { useConfirm } from "./ConfirmDialog";
import {
  hasServerDrive,
  useDriveReady,
  findFolderFor,
  folderIdFromLink,
  getDriveToken,
  pickDriveFolder,
  pickPdfFromDrive,
  pickPdfsFromFolder,
} from "./googleDrive";
import { guessDocType } from "./docTypeGuess";
import { MATCH_LABELS, type FolderResult } from "./folderMatch";
import { useUploadQueue } from "./uploadQueue";
import { FolderReader } from "./FolderReader";
import {
  DOCUMENT_TYPE_LABELS,
  LEGACY_DOCUMENT_TYPES,
  DOCUMENT_GROUPS,
  documentGroup,
  type DocumentChecklistItem,
  type DocumentType,
  type Shipment,
  type ShipmentDocument,
  docShort,
} from "./types";

const short = docShort;

const UPLOAD_TYPES = (Object.keys(DOCUMENT_TYPE_LABELS) as DocumentType[]).filter(
  (t) => !LEGACY_DOCUMENT_TYPES.includes(t),
);

/** Documents whose PDF is read on upload (fills BE/duty/CFS fields). */
const READ_ON_UPLOAD: DocumentType[] = [
  "assessed_bill_of_entry",
  "ooc_bill_of_entry",
  "gatepass_bill_of_entry",
  "cfs_proforma_invoice",
  "cfs_tax_invoice",
  "shipping_line_proforma",
  "shipping_line_invoice",
  "shipping_line_receipt",
  "cfs_receipt",
];

export default function DocumentManagerPanel({
  shipment,
  onShipmentChanged,
  initialType,
}: {
  shipment: Shipment;
  onShipmentChanged: () => void;
  /** Money card → Upload: the slot to pick (e.g. the CFS tax invoice) */
  initialType?: DocumentType;
}) {
  const [checklist, setChecklist] = useState<DocumentChecklistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [docType, setDocType] = useState<DocumentType>(initialType ?? "bl_copy");
  const typeSelect = useRef<HTMLSelectElement>(null);
  useEffect(() => {
    if (!initialType) return;
    setDocType(initialType);
    typeSelect.current?.scrollIntoView({ block: "center" });
    typeSelect.current?.focus({ preventScroll: true });
  }, [initialType]);
  const [file, setFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpload, setLastUpload] = useState<ShipmentDocument | null>(null);

  function refresh() {
    setLoading(true);
    getDocumentChecklist(shipment.id)
      .then(setChecklist)
      .finally(() => setLoading(false));
  }

  useEffect(refresh, [shipment.id]);

  // documents are added in the background (tray in the corner); refresh when ours finish
  const queue = useUploadQueue();
  const shipmentLabel = shipment.job ? `Job ${shipment.job}` : shipment.mbl;
  useEffect(
    () =>
      queue.onFinished((job) => {
        if (job.shipmentId !== shipment.id) return;
        if (job.status === "done") {
          if (job.showResult && job.doc) setLastUpload(job.doc);
          refresh();
          onShipmentChanged(); // fields read from the PDF may have changed the shipment
        } else if (job.showResult) {
          setError(`Couldn't add ${job.fileName}: ${job.error}`);
        }
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [shipment.id, queue.onFinished],
  );

  async function handlePickFromDrive() {
    setError(null);
    let picked;
    try {
      picked = await pickPdfFromDrive(shipment.drive_folder_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't open Google Drive.");
      return;
    }
    if (!picked) return; // cancelled
    const { id, accessToken, name } = picked;
    const type = docType;
    queue.enqueue([{
      shipmentId: shipment.id, shipmentLabel, fileName: name, typeLabel: DOCUMENT_TYPE_LABELS[type], showResult: true,
      run: () => addDocumentFromDrive(shipment.id, type, id, accessToken),
    }]);
  }

  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const confirm = useConfirm();
  const driveReady = useDriveReady();

  async function handleRemove(doc: ShipmentDocument) {
    const ok = await confirm({
      title: "Remove document?",
      message: `Remove ${doc.generated_filename} from this shipment? It moves to Recently deleted — the admin can restore it.`,
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) return;
    setError(null);
    try {
      await removeDocument(shipment.id, doc.id);
      setLastUpload(null);
      refresh();
    } catch {
      setError(`Couldn't remove ${doc.generated_filename}.`);
    }
  }

  async function handleReread(doc: ShipmentDocument) {
    setError(null);
    setUploading(true);
    try {
      setLastUpload(await rereadDocument(shipment.id, doc.id));
      refresh();
      onShipmentChanged();
    } catch {
      setError(`Couldn't re-read ${doc.generated_filename}.`);
    } finally {
      setUploading(false);
    }
  }

  async function handleUpload(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setError(null);
    // Linked Drive folder: the server saves the renamed file there itself; only without
    // its own Drive connection does this need the user's Google sign-in
    let driveToken: string | undefined;
    if (shipment.drive_folder_id && driveReady && !(await hasServerDrive())) {
      try {
        driveToken = await getDriveToken();
      } catch {
        driveToken = undefined; // saved here only; the result banner says so
      }
    }
    const [f, type] = [file, docType];
    queue.enqueue([{
      shipmentId: shipment.id, shipmentLabel, fileName: f.name, typeLabel: DOCUMENT_TYPE_LABELS[type], showResult: true,
      run: () => uploadDocument(shipment.id, type, f, driveToken),
    }]);
    setFile(null);
    setFileInputKey((k) => k + 1); // ready for the next file straight away
  }

  const mandatory = checklist.filter((c) => c.required && !c.optional);
  const uploadedCount = mandatory.filter((c) => c.uploaded).length;
  const optionalCount = checklist.filter((c) => c.required && c.optional).length;

  // --- several files from the shipment's own Drive folder, each marked as one of our documents ---
  const [picked, setPicked] = useState<{ files: { id: string; name: string }[]; accessToken: string } | null>(null);
  async function handlePickFromFolder() {
    if (!shipment.drive_folder_id) return;
    setError(null);
    try {
      const got = await pickPdfsFromFolder(shipment.drive_folder_id);
      if (got) setPicked(got);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't open Google Drive.");
    }
  }

  return (
    <div className="doc-manager">
      {!shipment.hs_code_id && (
        <div className="auth-error">
          No HS code assigned to this shipment — the required-document checklist can't populate until one is set on
          the Overview tab.
        </div>
      )}

      <DriveFolderBar shipment={shipment} onChanged={onShipmentChanged} onPickFiles={handlePickFromFolder} />
      <FolderReader
        shipment={shipment}
        onChanged={() => {
          refresh();
          onShipmentChanged();
        }}
      />
      {picked && (
        <AssignDriveFiles
          shipment={shipment}
          files={picked.files}
          accessToken={picked.accessToken}
          missing={mandatory.filter((c) => !c.uploaded).map((c) => c.document_type)}
          onDone={() => {
            setPicked(null);
            refresh();
            onShipmentChanged();
          }}
        />
      )}

      {shipment.hs_code_id != null && (
        <p className="tracker-subtitle">
          Required {uploadedCount}/{mandatory.length}
          {optionalCount > 0 && <span className="field-note"> · + {optionalCount} optional</span>}
        </p>
      )}

      {!user?.read_only && (
      <form className="add-shipment-form" onSubmit={handleUpload}>
        <select ref={typeSelect} aria-label="Document type" value={docType} onChange={(e) => setDocType(e.target.value as DocumentType)}>
          {DOCUMENT_GROUPS.map((g) => (
            <optgroup key={g.id} label={g.label}>
              {g.types.filter((t) => UPLOAD_TYPES.includes(t)).map((t) => (
                <option key={t} value={t}>
                  {DOCUMENT_TYPE_LABELS[t]}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        <input
          key={fileInputKey}
          type="file"
          accept="application/pdf"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          required
        />
        <button type="submit" disabled={uploading || !file}>
          {uploading ? "Adding…" : "Upload"}
        </button>
        <span className="upload-or">or</span>
        <button
          type="button"
          className="btn-secondary drive-btn"
          onClick={handlePickFromDrive}
          disabled={uploading || !driveReady}
          title={driveReady ? "Pick a PDF already saved in Google Drive" : "Google Drive isn't set up yet — see PROGRESS.md"}
        >
          <DriveIcon /> Choose from Google Drive
        </button>
      </form>
      )}
      {READ_ON_UPLOAD.includes(docType) && (
        <p className="tracker-subtitle">
          This document is read on upload — BE / duty / CFS details fill in automatically.
          {(docType.startsWith("cfs_") || docType.startsWith("shipping_line_")) &&
            " You can add several; their amounts are added up. Misread figures can be corrected on the Overview."}
          {docType.endsWith("_receipt") && " Receipts record the amount actually paid."}
        </p>
      )}
      {error && <div className="auth-error">{error}</div>}

      {lastUpload && <UploadResult doc={lastUpload} onClose={() => setLastUpload(null)} />}

      {loading ? (
        <div className="tracker-empty">Loading…</div>
      ) : checklist.length === 0 ? (
        <div className="tracker-empty">No documents yet.</div>
      ) : (
        // two columns of group cards (client, 2026-09-29): basic + CFS | customs + shipping line
        <div className="doc-columns">
          {[["basic", "cfs"], ["customs", "line", "other"]].map((ids) => (
            <div className="doc-col" key={ids[0]}>
              {DOCUMENT_GROUPS.filter((g) => ids.includes(g.id)).map((g) => {
                const rows = checklist
                  .filter((r) => documentGroup(r.document_type).id === g.id)
                  .sort((a, b) => g.types.indexOf(a.document_type) - g.types.indexOf(b.document_type));
                if (rows.length === 0) return null;
                // "required x/y": optional papers counted apart, muted, so they don't look like gaps
                const req = rows.filter((r) => r.required && !r.optional);
                const done = req.filter((r) => r.uploaded).length;
                const extra = rows.length - req.length;
                return (
                  <section className="doc-group tracker-grid-wrap" key={g.id}>
                    <div className="doc-group-head">
                      <span className={`doc-marker doc-marker-${g.id}`}>{g.marker}</span> {g.label}
                      <span className="doc-group-count">
                        {req.length > 0 && `required ${done}/${req.length}`}
                        {extra > 0 && <span className="muted"> + {extra} optional</span>}
                      </span>
                    </div>
                    <table className="tracker-grid doc-table">
                      <colgroup>
                        <col className="doc-col-name" />
                        <col className="doc-col-status" />
                        <col className="doc-col-file" />
                        <col className="doc-col-when" />
                      </colgroup>
                      <thead>
                        <tr>
                          <th>Document</th>
                          <th>Status</th>
                          <th>File</th>
                          <th>Uploaded</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((row) => {
                const missing = !row.uploaded;
                const coveredByCombined = row.document && row.document.document_type !== row.document_type;
                return (
                  <tr key={row.document_type} className={row.required && !row.optional && missing ? "doc-row-missing" : ""}>
                    <td>
                      <span className={`doc-marker doc-marker-${g.id}`}>{g.marker}</span>{" "}
                      <span title={DOCUMENT_TYPE_LABELS[row.document_type]}>{short(row.document_type)}</span>
                    </td>
                    <td>
                      <span className={`status-pill ${row.uploaded ? "status-cleared" : row.required && !row.optional ? "status-missing" : ""}`}>
                        {row.uploaded ? "Uploaded" : !row.required ? "Not needed" : row.optional ? "Optional" : "Not attached"}
                      </span>
                      {coveredByCombined && (
                        <span className="tracker-subtitle"> in {short(row.document!.document_type)}</span>
                      )}
                    </td>
                    <td>
                      {row.documents.length === 0
                        ? "—"
                        : row.documents.map((d, n) => (
                            <div key={d.id} className="doc-file-line">
                              {/* the file name is on hover only — it takes unpredictable width (client, 2026-09-30) */}
                              <span className="doc-file-chip" title={d.generated_filename}>
                                {row.documents.length > 1 ? `File ${n + 1}` : "File"}
                              </span>{" "}
                              <PdfKindBadge kind={d.pdf_kind} />
                              {d.extraction?.fields?.gst_missing === true && (
                                <span className="pdf-kind pdf-kind-scanned" title="These invoices always have GST — check the figures (Overview → correct amounts)">
                                  No GST
                                </span>
                              )}
                              {d.extraction?.fields?.bl_mismatch === true && (
                                <span
                                  className="pdf-kind pdf-kind-scanned"
                                  title={`BL on this invoice (${String(d.extraction?.fields?.bl_no ?? "")}) isn't this shipment's MBL / HBL — not counted in the totals until it matches`}
                                >
                                  BL ≠ shipment
                                </span>
                              )}
                              {d.extraction?.duplicate_of && (
                                <span className="pdf-kind pdf-kind-partly" title="Same invoice number as another file here — its amounts are counted once">
                                  Duplicate
                                </span>
                              )}{" "}
                              <button type="button" className="link-btn" onClick={() => openDocumentFile(shipment.id, d.id)}>
                                View
                              </button>
                              {d.drive_sync_pending && (
                                <span className="exception-badge" title={`Not in Drive yet — retrying. ${d.drive_error ?? ""}`}>
                                  {" "}Drive pending
                                </span>
                              )}
                              {d.drive_link && (
                                <>
                                  {" "}
                                  <a href={d.drive_link} target="_blank" rel="noreferrer" className="drive-link" title="Open in Google Drive">
                                    Drive ↗
                                  </a>
                                </>
                              )}
                            </div>
                          ))}
                    </td>
                    <td>
                      {row.documents.length === 0
                        ? "—"
                        : row.documents.map((d) => (
                            <div key={d.id} className="doc-file-line">
                              <span title={fmtWhen(d.uploaded_at, true)}>
                                {fmtWhenDay(d.uploaded_at)}
                              </span>
                              {READ_ON_UPLOAD.includes(d.document_type) && (
                                <>
                                  {" "}
                                  <button
                                    type="button"
                                    className="link-btn"
                                    disabled={uploading}
                                    hidden={!!user?.read_only}
                                    title="Re-read: read this document again and update the shipment"
                                    aria-label="Re-read"
                                    onClick={() => handleReread(d)}
                                  >
                                    ↻
                                  </button>
                                </>
                              )}
                              {isAdmin && !user?.read_only && (
                                <>
                                  {" "}
                                  <button
                                    type="button"
                                    className="link-btn link-danger"
                                    title="Remove this document from the shipment"
                                    aria-label="Remove"
                                    onClick={() => handleRemove(d)}
                                  >
                                    ✕
                                  </button>
                                </>
                              )}
                            </div>
                          ))}
                    </td>
                  </tr>
                );
                        })}
                      </tbody>
                    </table>
                  </section>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DriveFolderBar({
  shipment,
  onChanged,
  onPickFiles,
}: {
  shipment: Shipment;
  onChanged: () => void;
  onPickFiles: () => void;
}) {
  const ro = !!useAuth().user?.read_only;
  const saveShipment = useSaveShipment();
  const driveReady = useDriveReady();
  const [link, setLink] = useState("");
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [finding, setFinding] = useState(false);
  const [found, setFound] = useState<FolderResult | null>(null);

  // "JOB <job> - <MBL/HBL>": search Drive, link automatically when exactly one folder matches both
  async function findInDrive() {
    setError(null);
    setFound(null);
    setFinding(true);
    try {
      const result = await findFolderFor(shipment);
      if (result.auto) await save(result.auto.id, result.auto.url);
      else setFound(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't search Google Drive.");
    } finally {
      setFinding(false);
    }
  }

  async function save(folderId: string | null, folderLink: string | null) {
    setError(null);
    try {
      await saveShipment(shipment, { drive_folder_id: folderId, drive_folder_link: folderLink });
      setEditing(false);
      setLink("");
      onChanged();
    } catch {
      setError("Couldn't save the folder.");
    }
  }
  async function choose() {
    setError(null);
    try {
      const f = await pickDriveFolder();
      if (f) await save(f.id, f.url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't open Google Drive.");
    }
  }
  function savePasted() {
    const id = folderIdFromLink(link);
    if (!id) return setError("That doesn't look like a Google Drive folder link.");
    save(id, link.trim().startsWith("http") ? link.trim() : `https://drive.google.com/drive/folders/${id}`);
  }

  if (shipment.drive_folder_id && !editing) {
    return (
      <div className="drive-folder-bar">
        <DriveIcon />
        <span>
          This shipment's{" "}
          <a href={shipment.drive_folder_link ?? "#"} target="_blank" rel="noreferrer">
            Drive folder ↗
          </a>
        </span>
        <button
          type="button"
          onClick={onPickFiles}
          disabled={!driveReady}
          title={driveReady ? "Select files already in this folder and mark which document each one is" : "Google Drive isn't set up yet — see PROGRESS.md"}
        >
          Pick files from this folder
        </button>
        <button type="button" className="link-btn" hidden={ro} onClick={() => setEditing(true)}>
          Change
        </button>
        <button type="button" className="link-btn" hidden={ro} onClick={() => save(null, null)}>
          Unlink
        </button>
      </div>
    );
  }
  if (ro) return null;
  return (
    <div className="drive-folder-bar drive-folder-unlinked">
      <DriveIcon />
      <span>Link this shipment's Drive folder:</span>
      <button
        type="button"
        onClick={findInDrive}
        disabled={!driveReady || finding}
        title={`Looks for a folder named like "JOB ${shipment.job || "<job>"} - ${shipment.mbl}"`}
      >
        {finding ? "Searching Drive…" : "Find in Drive"}
      </button>
      <button
        type="button"
        className="btn-secondary"
        onClick={choose}
        disabled={!driveReady}
        title={driveReady ? "" : "Google Drive isn't set up yet — see PROGRESS.md"}
      >
        Choose folder
      </button>
      <span className="upload-or">or paste its link</span>
      <input
        placeholder="https://drive.google.com/drive/folders/…"
        value={link}
        onChange={(e) => setLink(e.target.value)}
      />
      <button type="button" className="btn-secondary" onClick={savePasted} disabled={!link.trim()}>
        Save
      </button>
      {editing && (
        <button type="button" className="link-btn" onClick={() => setEditing(false)}>
          Cancel
        </button>
      )}
      {error && <span className="auth-error">{error}</span>}
      {found && (
        <div className="folder-candidates">
          {found.candidates.length === 0 ? (
            <span className="field-note">
              No folder found with this shipment's MBL/HBL or "JOB {shipment.job || "?"}" in its name — choose it by hand.
            </span>
          ) : (
            <>
              <span className="field-note">Not sure which one — please choose:</span>
              {found.candidates.map(({ folder, match }) => (
                <div key={folder.id} className="folder-candidate">
                  <a href={folder.url} target="_blank" rel="noreferrer">
                    {folder.name} ↗
                  </a>
                  <span className={match === "verified" || match === "no-job" ? "field-note" : "exception-badge"}>
                    {MATCH_LABELS[match]}
                  </span>
                  <button type="button" className="btn-secondary" onClick={() => save(folder.id, folder.url)}>
                    Link
                  </button>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function DriveIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 87.3 78" aria-hidden="true">
      <path fill="#0066da" d="M6.6 66.85l3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3L27.5 53H0c0 1.55.4 3.1 1.2 4.5z" />
      <path fill="#00ac47" d="M43.65 25L29.9 1.2c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44A9.06 9.06 0 000 53h27.5z" />
      <path fill="#ea4335" d="M73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5H59.8l5.85 11.5z" />
      <path fill="#00832d" d="M43.65 25L57.4 1.2C56.05.4 54.5 0 52.9 0H34.4c-1.6 0-3.15.45-4.5 1.2z" />
      <path fill="#2684fc" d="M59.8 53H27.5L13.75 76.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z" />
      <path fill="#ffba00" d="M73.4 26.5l-12.7-22c-.8-1.4-1.95-2.5-3.3-3.3L43.65 25 59.8 53h27.45c0-1.55-.4-3.1-1.2-4.5z" />
    </svg>
  );
}

function UploadResult({ doc, onClose }: { doc: ShipmentDocument; onClose: () => void }) {
  const ex = doc.extraction;
  const read = ex && (ex.updated.length > 0 || ex.notes.length > 0);
  return (
    <div className="upload-result">
      <div className="upload-result-head">
        <strong>{doc.generated_filename}</strong>
        <button type="button" className="link-btn" onClick={onClose} aria-label="Dismiss">
          ✕
        </button>
      </div>
      {read ? (
        <>
          {ex!.updated.length > 0 && <p>Updated on the shipment: {ex!.updated.join(", ")}</p>}
          {ex!.notes.map((n) => (
            <p key={n} className="upload-result-note">
              ⚠ {n}
            </p>
          ))}
        </>
      ) : (
        <p className="tracker-subtitle">Nothing on the shipment changed from this document.</p>
      )}
    </div>
  );
}

/**
 * Files picked from the shipment's Drive folder: say which document each one is (guessed
 * from its name), then they're added — read like an upload, linked to the original in
 * Drive (never copied or renamed there).
 */
function AssignDriveFiles({
  shipment,
  files,
  accessToken,
  missing,
  onDone,
}: {
  shipment: Shipment;
  files: { id: string; name: string }[];
  accessToken: string;
  missing: DocumentType[];
  onDone: () => void;
}) {
  const [types, setTypes] = useState<Record<string, DocumentType | "">>(() =>
    Object.fromEntries(files.map((f) => [f.id, guessDocType(f.name) ?? ""])),
  );
  const chosen = files.filter((f) => types[f.id]);
  const stillMissing = missing.filter((t) => !Object.values(types).includes(t));

  const queue = useUploadQueue();
  function addAll() {
    // handed to the background queue: carry on working, the tray shows progress
    queue.enqueue(
      chosen.map((f) => {
        const type = types[f.id] as DocumentType;
        return {
          shipmentId: shipment.id,
          shipmentLabel: shipment.job ? `Job ${shipment.job}` : shipment.mbl,
          fileName: f.name,
          typeLabel: DOCUMENT_TYPE_LABELS[type],
          run: () => addDocumentFromDrive(shipment.id, type, f.id, accessToken),
        };
      }),
    );
    onDone();
  }

  return (
    <div className="confirm-backdrop">
      <div className="confirm-dialog assign-dialog" role="dialog" aria-modal="true" aria-labelledby="assign-title">
        <h2 id="assign-title">Mark the files from Drive</h2>
        <p>
          Choose what each file is. They're added in the background (you can keep working — the tray in the corner
          shows progress), read like an upload, and linked to the original in your Drive folder — nothing is
          copied, moved or renamed there. Leave a file on "Skip" to ignore it.
        </p>
        <table className="rates-table">
          <tbody>
            {files.map((f) => (
              <tr key={f.id}>
                <td className="assign-name">{f.name}</td>
                <td>
                  <select
                    value={types[f.id]}
                    onChange={(e) => setTypes((t) => ({ ...t, [f.id]: e.target.value as DocumentType | "" }))}
                  >
                    <option value="">Skip</option>
                    {DOCUMENT_GROUPS.map((g) => (
                      <optgroup key={g.id} label={g.label}>
                        {g.types.filter((t) => UPLOAD_TYPES.includes(t)).map((t) => (
                          <option key={t} value={t}>
                            {DOCUMENT_TYPE_LABELS[t]}
                            {missing.includes(t) ? " (needed)" : ""}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {stillMissing.length > 0 && (
          <p className="field-note">
            Still needed after these: {stillMissing.map(short).join(", ")}
          </p>
        )}
        <div className="confirm-actions">
          <button type="button" className="btn-secondary" onClick={onDone}>
            Cancel
          </button>
          <button type="button" onClick={addAll} disabled={chosen.length === 0}>
            Add {chosen.length} document{chosen.length === 1 ? "" : "s"}
          </button>
        </div>
      </div>
    </div>
  );
}

const PDF_KINDS = {
  digital: ["Digital", "Text can be read — details fill in automatically"],
  partly: ["Partly scanned", "Some pages are scans — only the text pages were read"],
  scanned: ["Scanned", "Pictures of pages — nothing could be read; check the details by hand"],
  unreadable: ["Unreadable", "Not a valid PDF, or password-protected"],
} as const;

/** Digital or scanned: whether the ERP could read the document's text. */
function PdfKindBadge({ kind }: { kind: ShipmentDocument["pdf_kind"] }) {
  if (!kind) return null;
  const [label, tip] = PDF_KINDS[kind];
  return (
    <span className={`pdf-kind pdf-kind-${kind}`} title={tip}>
      {label}
    </span>
  );
}
