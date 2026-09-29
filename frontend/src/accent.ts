/**
 * Look (client, 2026-09-29/30): theme — calm light, Dim (semi-dark) or Dark — and accent
 * colour, chosen in the sidebar and remembered per browser. Set as data-theme /
 * data-accent on <html>; the colours live in index.css.
 */
export const ACCENTS = [
  { id: "sage", label: "Sage (calm)", color: "#3F7F6E" },
  { id: "orange", label: "Clarus orange", color: "#C8703C" },
  { id: "indigo", label: "Indigo", color: "#5E6AD2" },
  { id: "blue", label: "Blue", color: "#2F6FEB" },
  { id: "graphite", label: "Graphite", color: "#3A3D42" },
] as const;
export type AccentId = (typeof ACCENTS)[number]["id"];

export const THEMES = [
  { id: "light", label: "Light" },
  { id: "dim", label: "Dim" },
  { id: "dark", label: "Dark" },
] as const;
export type ThemeId = (typeof THEMES)[number]["id"];

const ACCENT_KEY = "clarus.accent";
const THEME_KEY = "clarus.theme";

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function write(key: string, v: string): void {
  try {
    localStorage.setItem(key, v);
  } catch {
    /* private window: just this page load */
  }
}

export function savedAccent(): AccentId {
  const v = read(ACCENT_KEY);
  return ACCENTS.some((a) => a.id === v) ? (v as AccentId) : "sage";
}

export function setAccent(id: AccentId): void {
  if (id === "sage") delete document.documentElement.dataset.accent;
  else document.documentElement.dataset.accent = id;
  write(ACCENT_KEY, id);
}

export function savedTheme(): ThemeId {
  const v = read(THEME_KEY);
  return THEMES.some((t) => t.id === v) ? (v as ThemeId) : "light";
}

export function setTheme(id: ThemeId): void {
  if (id === "light") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = id;
  write(THEME_KEY, id);
}

export function applySavedAccent(): void {
  setAccent(savedAccent());
  setTheme(savedTheme());
}
