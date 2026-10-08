import { useEffect, useState, type ReactNode } from "react";

/**
 * The green / red message box. A green (done) one disappears after a few seconds (client, 2026-10-08);
 * a red one stays until the next message. `stamp` is the message object: a new one shows the box again.
 */
export default function Toast({ ok, stamp, children, className = "" }: { ok: boolean; stamp: unknown; children: ReactNode; className?: string }) {
  const [gone, setGone] = useState(false);
  useEffect(() => {
    setGone(false);
    if (!ok) return;
    const t = window.setTimeout(() => setGone(true), 3000);
    return () => window.clearTimeout(t);
  }, [ok, stamp]);
  if (gone) return null;
  return (
    <div role="status" aria-live="polite" className={`grid-toast ${ok ? "grid-toast-ok" : "grid-toast-error"}${className ? ` ${className}` : ""}`}>
      {children}
    </div>
  );
}
