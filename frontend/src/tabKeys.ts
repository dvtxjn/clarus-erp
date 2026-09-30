import type { KeyboardEvent } from "react";

/** Arrow / Home / End keys move between tabs in a role="tablist" (WAI-ARIA tabs pattern). */
export function tabKeys(e: KeyboardEvent<HTMLElement>) {
  const tabs = [...e.currentTarget.querySelectorAll<HTMLElement>('[role="tab"]:not([disabled])')];
  const i = tabs.indexOf(document.activeElement as HTMLElement);
  if (i < 0) return;
  const next =
    e.key === "ArrowRight" ? (i + 1) % tabs.length
    : e.key === "ArrowLeft" ? (i - 1 + tabs.length) % tabs.length
    : e.key === "Home" ? 0
    : e.key === "End" ? tabs.length - 1
    : -1;
  if (next < 0) return;
  e.preventDefault();
  tabs[next].focus();
  tabs[next].click();
}
