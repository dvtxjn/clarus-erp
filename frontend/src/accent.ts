/**
 * Accent colour (design refresh, 2026-09-29). Temporary: a switcher in the sidebar lets the
 * client compare colours on real data; the choice is remembered per browser. Once one is
 * picked it becomes the default in index.css and the switcher goes.
 */
export const ACCENTS = [
  { id: "orange", label: "Clarus orange", color: "#D9621C" },
  { id: "indigo", label: "Indigo", color: "#5E6AD2" },
  { id: "blue", label: "Blue", color: "#2F6FEB" },
  { id: "green", label: "Green", color: "#1F8A5B" },
  { id: "graphite", label: "Graphite", color: "#2B2D31" },
] as const;
export type AccentId = (typeof ACCENTS)[number]["id"];

const KEY = "clarus.accent";

export function savedAccent(): AccentId {
  try {
    const v = localStorage.getItem(KEY);
    return ACCENTS.some((a) => a.id === v) ? (v as AccentId) : "orange";
  } catch {
    return "orange";
  }
}

export function setAccent(id: AccentId): void {
  if (id === "orange") delete document.documentElement.dataset.accent;
  else document.documentElement.dataset.accent = id;
  try {
    localStorage.setItem(KEY, id);
  } catch {
    /* private window: just this page load */
  }
}

export function applySavedAccent(): void {
  setAccent(savedAccent());
}
