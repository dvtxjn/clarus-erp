import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

/** Elements whose text may be cut with "…": they get the full text as a tooltip, and only when it is cut. */
const TRUNCATES = ".key-value, .key-sub, .money-value, .money-meta, .inv-name, .edit-value, .next-step-detail, [data-overflow-tip]";

/**
 * One tooltip for the whole app: hovering (or focusing) cut-off text shows it in full after 300ms,
 * 6px under it. Text that fits shows nothing — no native title on these.
 */
export default function OverflowTip() {
  const [tip, setTip] = useState<{ text: string; top: number; left: number } | null>(null);
  const timer = useRef(0);
  useEffect(() => {
    const hide = () => {
      window.clearTimeout(timer.current);
      setTip(null);
    };
    const show = (e: Event) => {
      const el = (e.target as Element | null)?.closest?.(TRUNCATES) as HTMLElement | null;
      hide();
      if (!el || el.scrollWidth <= el.clientWidth + 1) return;
      const text = el.dataset.overflowTip || el.textContent?.trim();
      if (!text) return;
      timer.current = window.setTimeout(() => {
        const r = el.getBoundingClientRect();
        setTip({ text, top: r.bottom + 6, left: Math.max(8, Math.min(r.left, window.innerWidth - 368)) });
      }, 300);
    };
    document.addEventListener("pointerover", show);
    document.addEventListener("focusin", show);
    document.addEventListener("pointerdown", hide);
    document.addEventListener("keydown", hide);
    window.addEventListener("scroll", hide, true);
    return () => {
      hide();
      document.removeEventListener("pointerover", show);
      document.removeEventListener("focusin", show);
      document.removeEventListener("pointerdown", hide);
      document.removeEventListener("keydown", hide);
      window.removeEventListener("scroll", hide, true);
    };
  }, []);
  if (!tip) return null;
  return createPortal(
    <div className="overflow-tip" role="tooltip" style={{ top: tip.top, left: tip.left }}>
      {tip.text}
    </div>,
    document.body,
  );
}
