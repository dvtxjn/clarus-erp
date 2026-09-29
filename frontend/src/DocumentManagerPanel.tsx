import { useEffect, useState, type FormEvent } from "react";
import axios from "axios";
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
  driveConfigured,
  folderIdFromLink,
  getDriveToken,
  pickDriveFolder,
  pickPdfFromDrive,
  pickPdfsFromFolder,
} from "./googleDrive";
import { guessDocType } from "./docTypeGuess";
import {
  DOCUMENT_TYPE_LABELS,
  LEGACY_DOCUMENT_TYPES,
  type DocumentChecklistItem,
  type DocumentType,
  type Shipment,
  type ShipmentDocument,
} from "./types";

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
}: {
  shipment: Shipment;
  onShipmentChanged: () => void;
}) {
  const [checklist, setChecklist] = useState<DocumentChecklistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [docType, setDocType] = useState<DocumentType>("bl_copy");
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
    setUploading(true);
    try {
      const doc: ShipmentDocument = await addDocumentFromDrive(shipment.id, docType, picked.id, picked.accessToken);
      setLastUpload(doc);
      refresh();
      onShipmentChanged();
    } catch (err) {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null;
      setError(typeof detail === "string" ? detail : `Couldn't add "${picked.name}" from Google Drive.`);
    } finally {
      setUploading(false);
    }
  }

  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const confirm = useConfirm();

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
    setUploading(true);
    try {
      // Linked Drive folder: also save the renamed file there (needs Google sign-in)
      let driveToken: string | undefined;
      if (shipment.drive_folder_id && driveConfigured) {
        try {
          driveToken = await getDriveToken();
        } catch {
          driveToken = undefined; // saved here only; the result banner says so
        }
      }
      const doc: ShipmentDocument = await uploadDocument(shipment.id, docType, file, driveToken);
      setLastUpload(doc);
      setFile(null);
      setFileInputKey((k) => k + 1);
      refresh();
      onShipmentChanged(); // fields read from the PDF may have changed the shipment
    } catch {
      setError("Upload failed — check the file and try again.");
    } finally {
      setUploading(false);
    }
  }

  const mandatory = checklist.filter((c) => c.required && !c.optional);
  const uploadedCount = mandatory.filter((c) => c.uploaded).length;

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
          {uploadedCount} of {mandatory.length} required documents uploaded
        </p>
      )}

      <form className="add-shipment-form" onSubmit={handleUpload}>
        <select value={docType} onChange={(e) => setDocType(e.target.value as DocumentType)}>
          {UPLOAD_TYPES.map((t) => (
            <option key={t} value={t}>
              {DOCUMENT_TYPE_LABELS[t]}
            </option>
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
          disabled={uploading || !driveConfigured}
          title={driveConfigured ? "Pick a PDF already saved in Google Drive" : "Google Drive isn't set up yet — see PROGRESS.md"}
        >
          <DriveIcon /> Choose from Google Drive
        </button>
      </form>
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
        <div className="tracker-grid-wrap">
          <table className="tracker-grid">
            <thead>
              <tr>
                <th>Document Type</th>
                <th>Required</th>
                <th>Status</th>
                <th>File</th>
                <th>Uploaded</th>
              </tr>
            </thead>
            <tbody>
              {checklist.map((row) => {
                const missing = !row.uploaded;
                const coveredByCombined = row.document && row.document.document_type !== row.document_type;
                return (
                  <tr key={row.document_type} className={row.required && !row.optional && missing ? "row-stuck" : ""}>
                    <td>{DOCUMENT_TYPE_LABELS[row.document_type]}</td>
                    <td>{!row.required ? "No" : row.optional ? "Optional" : "Yes"}</td>
                    <td>
                      <span className={`status-pill ${row.uploaded ? "status-cleared" : ""}`}>
                        {row.uploaded ? "Uploaded" : row.optional ? "Not uploaded" : "Missing"}
                      </span>
                      {coveredByCombined && (
                        <span className="tracker-subtitle"> in {DOCUMENT_TYPE_LABELS[row.document!.document_type]}</span>
                      )}
                    </td>
                    <td>
                      {row.documents.length === 0
                        ? "—"
                        : row.documents.map((d) => (
                            <div key={d.id} className="doc-file-line">
                              {d.generated_filename}{" "}
                              <button type="button" className="link-btn" onClick={() => openDocumentFile(shipment.id, d.id)}>
                                View
                              </button>
                              {d.drive_sync_pending && (
                                <span className="exception-badge" title={d.drive_error ?? ""}>
                                  {" "}not in Drive yet — retrying
                                </span>
                              )}
                              {d.drive_link && (
                                <>
                                  {" "}
                                  <a href={d.drive_link} target="_blank" rel="noreferrer" className="drive-link">
                                    open in Drive ↗
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
                              {new Date(d.uploaded_at).toLocaleString()}
                              {READ_ON_UPLOAD.includes(d.document_type) && (
                                <>
                                  {" "}
                                  <button
                                    type="button"
                                    className="link-btn"
                                    disabled={uploading}
                                    title="Read this document again and update the shipment"
                                    onClick={() => handleReread(d)}
                                  >
                                    Re-read
                                  </button>
                                </>
                              )}
                              {isAdmin && (
                                <>
                                  {" "}
                                  <button
                                    type="button"
                                    className="link-btn link-danger"
                                    title="Remove this document from the shipment"
                                    onClick={() => handleRemove(d)}
                                  >
                                    Remove
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
  const saveShipment = useSaveShipment();
  const [link, setLink] = useState("");
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
          disabled={!driveConfigured}
          title={driveConfigured ? "Select files already in this folder and mark which document each one is" : "Google Drive isn't set up yet — see PROGRESS.md"}
        >
          Pick files from this folder
        </button>
        <button type="button" className="link-btn" onClick={() => setEditing(true)}>
          Change
        </button>
        <button type="button" className="link-btn" onClick={() => save(null, null)}>
          Unlink
        </button>
      </div>
    );
  }
  return (
    <div className="drive-folder-bar drive-folder-unlinked">
      <DriveIcon />
      <span>Link this shipment's Drive folder:</span>
      <button
        type="button"
        className="btn-secondary"
        onClick={choose}
        disabled={!driveConfigured}
        title={driveConfigured ? "" : "Google Drive isn't set up yet — see PROGRESS.md"}
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
  const [status, setStatus] = useState<Record<string, "adding" | "ok" | string>>({});
  const [busy, setBusy] = useState(false);
  const chosen = files.filter((f) => types[f.id]);
  const stillMissing = missing.filter((t) => !Object.values(types).includes(t));
  const finished = files.length > 0 && files.every((f) => status[f.id] === "ok" || !types[f.id]) && !busy;

  async function addAll() {
    setBusy(true);
    for (const f of chosen) {
      if (status[f.id] === "ok") continue;
      setStatus((s) => ({ ...s, [f.id]: "adding" }));
      try {
        await addDocumentFromDrive(shipment.id, types[f.id] as DocumentType, f.id, accessToken);
        setStatus((s) => ({ ...s, [f.id]: "ok" }));
      } catch (err) {
        const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null;
        setStatus((s) => ({ ...s, [f.id]: typeof detail === "string" ? detail : "Couldn't add this file" }));
      }
    }
    setBusy(false);
  }

  return (
    <div className="confirm-backdrop">
      <div className="confirm-dialog assign-dialog" role="dialog" aria-modal="true" aria-labelledby="assign-title">
        <h2 id="assign-title">Mark the files from Drive</h2>
        <p>
          Choose what each file is. They're read like an upload and linked to the original in your Drive folder —
          nothing is copied, moved or renamed there. Leave a file on "Skip" to ignore it.
        </p>
        <table className="rates-table">
          <tbody>
            {files.map((f) => (
              <tr key={f.id}>
                <td className="assign-name">{f.name}</td>
                <td>
                  <select
                    value={types[f.id]}
                    disabled={busy || status[f.id] === "ok"}
                    onChange={(e) => setTypes((t) => ({ ...t, [f.id]: e.target.value as DocumentType | "" }))}
                  >
                    <option value="">Skip</option>
                    {UPLOAD_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {DOCUMENT_TYPE_LABELS[t]}
                        {missing.includes(t) ? " (needed)" : ""}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="assign-status">
                  {status[f.id] === "adding" ? "Adding…" : status[f.id] === "ok" ? "✓ Added" : status[f.id] ?? ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {stillMissing.length > 0 && (
          <p className="field-note">
            Still needed after these: {stillMissing.map((t) => DOCUMENT_TYPE_LABELS[t]).join(", ")}
          </p>
        )}
        <div className="confirm-actions">
          <button type="button" className="btn-secondary" onClick={onDone} disabled={busy}>
            {finished ? "Close" : "Cancel"}
          </button>
          {!finished && (
            <button type="button" onClick={addAll} disabled={busy || chosen.length === 0}>
              {busy ? "Adding…" : `Add ${chosen.length} document${chosen.length === 1 ? "" : "s"}`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
