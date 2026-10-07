import { useEffect, useRef, type RefObject } from "react";

/**
 * Close a popover / menu / sheet on a press outside `ref` or on Escape. Escape is marked handled
 * (preventDefault) so a layer under it — the peek — stays open. `ref: null` = Escape only.
 */
export function useDismiss(ref: RefObject<HTMLElement | null> | null, open: boolean, close: () => void) {
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => {
      const el = ref?.current;
      if (el && !el.contains(e.target as Node)) closeRef.current();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      e.preventDefault();
      closeRef.current();
    };
    if (ref) document.addEventListener("pointerdown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", down);
      document.removeEventListener("keydown", key);
    };
  }, [ref, open]);
}
