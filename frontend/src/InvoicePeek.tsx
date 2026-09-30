import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { invoicePdfUrl } from "./api";

/**
 * Invoicing page (client, 2026-09-30): clicking an invoice shows it first, with the way on —
 * to the shipment's Overview, or to this invoice inside the shipment to edit it.
 */
export type PeekTarget = {
  kind: "final" | "proforma";
  id: number;
  title: string;
  shipmentId: number;
  proformaId: number | null;
};

export default function InvoicePeek({ target, onClose }: { target: PeekTarget; onClose: () => void }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let made: string | null = null;
    let live = true;
    setUrl(null);
    setError(false);
    invoicePdfUrl(target.kind, target.id)
      .then((u) => {
        made = u;
        if (live) setUrl(u);
        else URL.revokeObjectURL(u);
      })
      .catch(() => live && setError(true));
    return () => {
      live = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [target.kind, target.id]);

  // Esc closes, focus stays in the dialog and goes back to the row afterwards
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    closeBtn.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab" && dialog.current) {
        const els = dialog.current.querySelectorAll<HTMLElement>("a[href], button:not([disabled])");
        const first = els[0];
        const last = els[els.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      before?.focus();
    };
  }, [onClose]);

  const invoiceTab = new URLSearchParams({ tab: "proforma" });
  if (target.proformaId) invoiceTab.set("pf", String(target.proformaId));
  if (target.kind === "final") invoiceTab.set("pane", "final");

  return (
    <div className="modal-backdrop inv-peek-backdrop" onMouseDown={onClose}>
      <div
        ref={dialog}
        className="inv-peek"
        role="dialog"
        aria-modal="true"
        aria-labelledby="inv-peek-title"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="inv-peek-bar">
          <h2 id="inv-peek-title" translate="no">
            {target.title}
          </h2>
          <span className="inv-peek-actions">
            <Link to={`/shipments/${target.shipmentId}`} className="btn-link btn-secondary">
              Go to shipment
            </Link>
            <Link to={`/shipments/${target.shipmentId}?${invoiceTab}`} className="btn-link">
              Go to invoice
            </Link>
            <button ref={closeBtn} type="button" className="peek-close" onClick={onClose} aria-label="Close preview" title="Close (Esc)">
              ✕
            </button>
          </span>
        </div>
        <div className="inv-peek-body">
          {error ? (
            <div className="tracker-empty">Couldn’t load the preview. Use “Go to invoice” to open it in the shipment.</div>
          ) : !url ? (
            <div className="tracker-empty">Loading preview…</div>
          ) : (
            <iframe src={url} title={`Preview of ${target.title}`} />
          )}
        </div>
      </div>
    </div>
  );
}
