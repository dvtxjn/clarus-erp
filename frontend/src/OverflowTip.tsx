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
    // the grid hides its own tooltip only when the mouse leaves the cell; if the cell moves away
    // (peek opens/closes, a menu opens, scroll) that never happens, so tell the cell the mouse left
    let gridCell: Element | null = null;
    const dropGridTip = () => {
      gridCell?.dispatchEvent(new MouseEvent("mouseleave"));
      gridCell = null;
      // a redrawn cell leaves its tooltip with no owner to hide it: hide what's still showing
      document.querySelectorAll<HTMLElement>(".ag-tooltip").forEach((t) => (t.style.display = "none"));
    };
    const hide = () => {
      window.clearTimeout(timer.current);
      setTip(null);
      dropGridTip();
    };
    // after a panel or menu opens/closes, the rows slide under a still mouse: no grid tooltip for
    // 0.5 s and until the mouse moves, and whatever popped up meanwhile is dropped
    let quietSince = 0;
    const quiet = () => {
      hide();
      quietSince = Date.now();
      document.body.classList.add("grid-tips-quiet");
    };
    const wake = () => {
      if (!document.body.classList.contains("grid-tips-quiet") || Date.now() - quietSince < 500) return;
      document.querySelectorAll<HTMLElement>(".ag-tooltip").forEach((t) => (t.style.display = "none"));
      document.body.classList.remove("grid-tips-quiet");
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") hide();
      else {
        window.clearTimeout(timer.current);
        setTip(null);
      }
    };
    const show = (e: Event) => {
      const cell = (e.target as Element | null)?.closest?.(".ag-cell") ?? null;
      if (cell !== gridCell) dropGridTip();
      if (e.type === "pointerover") gridCell = cell;
      const el = (e.target as Element | null)?.closest?.(TRUNCATES) as HTMLElement | null;
      window.clearTimeout(timer.current);
      setTip(null);
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
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", hide, true);
    window.addEventListener("tips:hide", quiet);
    document.addEventListener("pointermove", wake);
    return () => {
      hide();
      document.removeEventListener("pointerover", show);
      document.removeEventListener("focusin", show);
      document.removeEventListener("pointerdown", hide);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("tips:hide", quiet);
      document.removeEventListener("pointermove", wake);
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
