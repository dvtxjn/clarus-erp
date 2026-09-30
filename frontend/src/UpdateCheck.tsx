import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { useUploadQueue } from "./uploadQueue";

/**
 * After a deploy, an open tab keeps running the old code until it's reloaded (client,
 * 2026-09-30: "this should not happen in production"). This checks which build the server
 * has — every 5 minutes and whenever the tab comes back into view — and when it's newer,
 * reloads on the next page change (nothing typed is lost that way), or offers a Reload button.
 * Never reloads while documents are still uploading.
 */
const BUILD_RE = /\/assets\/index-[\w-]+\.js/;

function runningBuild(): string | null {
  for (const s of Array.from(document.scripts)) {
    const m = s.src.match(BUILD_RE);
    if (m) return m[0];
  }
  return null; // the dev server: nothing to compare
}

async function serverBuild(): Promise<string | null> {
  try {
    const r = await fetch("/", { headers: { Accept: "text/html" }, cache: "no-store" });
    if (!r.ok) return null;
    return (await r.text()).match(BUILD_RE)?.[0] ?? null;
  } catch {
    return null; // offline: try again later
  }
}

export default function UpdateCheck() {
  const [stale, setStale] = useState(false);
  const { pathname } = useLocation();
  const first = useRef(pathname);
  const { jobs } = useUploadQueue();
  const busy = jobs.some((j) => j.status === "queued" || j.status === "running");

  useEffect(() => {
    const mine = runningBuild();
    if (!mine) return;
    let last = 0;
    const check = async () => {
      if (document.visibilityState !== "visible" || Date.now() - last < 30_000) return;
      last = Date.now();
      const theirs = await serverBuild();
      if (theirs && theirs !== mine) setStale(true);
    };
    const timer = window.setInterval(check, 5 * 60_000);
    document.addEventListener("visibilitychange", check);
    window.addEventListener("focus", check);
    // a page of the old build whose files are gone after the deploy: load the new one
    const preload = () => window.location.reload();
    window.addEventListener("vite:preloadError", preload);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", check);
      window.removeEventListener("focus", check);
      window.removeEventListener("vite:preloadError", preload);
    };
  }, []);

  // moving to another page is the safe moment: reload there instead
  useEffect(() => {
    if (stale && !busy && pathname !== first.current) window.location.reload();
    first.current = pathname;
  }, [pathname, stale, busy]);

  if (!stale) return null;
  return (
    <div className="update-banner" role="status" aria-live="polite">
      <span>A new version of the ERP is live.</span>
      <button type="button" onClick={() => window.location.reload()} disabled={busy} title={busy ? "Wait for the uploads to finish" : undefined}>
        Reload
      </button>
    </div>
  );
}
