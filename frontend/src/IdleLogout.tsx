import { useEffect, useRef, useState } from "react";
import { IDLE_MS, lastActive, markActive } from "./AuthContext";

const WARN_MS = 60 * 1000;

/**
 * Logs out after 30 minutes with no mouse, keyboard, touch or scroll in any ERP tab (client, 2026-09-30),
 * with a minute's warning. Live updates arriving on screen don't count as activity.
 */
export default function IdleLogout() {
  const [left, setLeft] = useState<number | null>(null);
  const stay = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let last = 0;
    const active = () => {
      const now = Date.now();
      if (now - last > 15000) {
        last = now;
        markActive(); // shared by every tab through localStorage
      }
    };
    const events = ["pointerdown", "keydown", "wheel", "touchstart", "scroll"] as const;
    events.forEach((e) => window.addEventListener(e, active, { passive: true, capture: true }));
    markActive();
    const tick = window.setInterval(() => {
      const idle = Date.now() - lastActive();
      if (idle >= IDLE_MS) {
        window.dispatchEvent(new CustomEvent("auth:ended", { detail: "Logged out after 30 minutes without activity." }));
      } else if (idle >= IDLE_MS - WARN_MS) {
        setLeft(Math.ceil((IDLE_MS - idle) / 1000));
      } else {
        setLeft(null);
      }
    }, 1000);
    return () => {
      events.forEach((e) => window.removeEventListener(e, active, { capture: true }));
      window.clearInterval(tick);
    };
  }, []);

  useEffect(() => {
    if (left !== null) stay.current?.focus();
  }, [left !== null]); // eslint-disable-line react-hooks/exhaustive-deps

  if (left === null) return null;
  return (
    <div className="modal-backdrop idle-backdrop" role="presentation">
      <div className="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="idle-title" aria-describedby="idle-text">
        <h2 id="idle-title">Still there?</h2>
        <p id="idle-text" aria-live="polite">
          You'll be logged out in {left} second{left === 1 ? "" : "s"} for inactivity.
        </p>
        <div className="confirm-actions">
          <button
            ref={stay}
            type="button"
            onClick={() => {
              markActive();
              setLeft(null);
            }}
          >
            Stay logged in
          </button>
        </div>
      </div>
    </div>
  );
}
