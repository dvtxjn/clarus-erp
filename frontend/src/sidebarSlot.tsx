import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/**
 * Page tools in the main sidebar (design refresh, 2026-09-29): a page can put its options
 * into the empty lower part of the sidebar instead of a column of its own (e.g. the
 * proforma's versions, actions and "Add line"). On narrow screens they stay in the page.
 */
export const SidebarSlotContext = createContext<HTMLElement | null>(null);

const WIDE = "(min-width: 1300px)";

function useWide(): boolean {
  const [wide, setWide] = useState(() => window.matchMedia(WIDE).matches);
  useEffect(() => {
    const m = window.matchMedia(WIDE);
    const on = () => setWide(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return wide;
}

export function SidebarPanel({ title, children }: { title: string; children: ReactNode }) {
  const slot = useContext(SidebarSlotContext);
  const wide = useWide();
  const panel = (
    <div className="sidebar-panel">
      <div className="app-nav-section">{title}</div>
      {children}
    </div>
  );
  return slot && wide ? createPortal(panel, slot) : panel;
}
