/**
 * Copy text to the clipboard. The async Clipboard API can be missing or blocked (http, an old
 * browser, a denied permission), so fall back to a hidden textarea + execCommand. Resolves
 * false when neither worked — the caller says so instead of pretending it copied.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* try the fallback */
  }
  const active = document.activeElement as HTMLElement | null;
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  let done = false;
  try {
    done = document.execCommand("copy");
  } catch {
    done = false;
  }
  ta.remove();
  active?.focus?.();
  return done;
}
