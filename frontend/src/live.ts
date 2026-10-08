/**
 * Live updates (Google-Sheets style): one stream per tab from GET /realtime/stream.
 * Uses fetch (not EventSource) so the login token goes in a header, never in a URL.
 * Reconnects by itself; after any reconnect the page reloads its rows ("resync").
 */
import { API_BASE_URL } from "./api";

export type LiveEvent =
  | { t: "hello"; uid: number; name: string }
  | { t: "s"; id: number; port: string | null; v: number; del: boolean; by: string | null }
  | { t: "p"; uid: number; name: string; sid: number | null; f: string | null; edit: boolean; tab: string | null }
  | { t: "resync" };

/** Identifies this browser tab (two tabs of the same person are two "people" here). */
export const TAB_ID = Math.random().toString(36).slice(2, 10);

export function connectLive(onEvent: (e: LiveEvent) => void, onStatus?: (live: boolean) => void): () => void {
  let stopped = false;
  let controller: AbortController | null = null;
  let attempt = 0;
  let first = true;

  async function run() {
    while (!stopped) {
      controller = new AbortController();
      try {
        const res = await fetch(`${API_BASE_URL}/realtime/stream`, {
          headers: { Authorization: `Bearer ${localStorage.getItem("access_token") ?? ""}` },
          signal: controller.signal,
        });
        if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
        onStatus?.(true);
        attempt = 0;
        if (!first) onEvent({ t: "resync" }); // missed events while disconnected
        first = false;
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let i: number;
          while ((i = buf.indexOf("\n\n")) >= 0) {
            const chunk = buf.slice(0, i);
            buf = buf.slice(i + 2);
            const data = chunk
              .split("\n")
              .filter((l) => l.startsWith("data:"))
              .map((l) => l.slice(5).trim())
              .join("");
            if (!data) continue; // ": ping"
            try {
              onEvent(JSON.parse(data) as LiveEvent);
            } catch {
              /* ignore a malformed event */
            }
          }
        }
      } catch {
        /* network / server restart: retry below */
      }
      onStatus?.(false);
      if (stopped) break;
      attempt += 1;
      await new Promise((r) => setTimeout(r, Math.min(15000, 1000 * 2 ** Math.min(attempt, 4))));
    }
  }
  run();
  return () => {
    stopped = true;
    controller?.abort();
  };
}

let presenceOn = true;
/** A view-only login doesn't announce where it is (the server refuses its POSTs anyway). */
export function setPresenceEnabled(on: boolean): void {
  presenceOn = on;
}

export function sendPresence(shipmentId: number | null, field: string | null, editing = false): void {
  if (!presenceOn) return;
  fetch(`${API_BASE_URL}/realtime/presence`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${localStorage.getItem("access_token") ?? ""}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ shipment_id: shipmentId, field, editing, tab: TAB_ID }),
    keepalive: true, // still sent when the tab is closing
  }).catch(() => {
    /* presence is best-effort */
  });
}

export const PRESENCE_COLORS = ["#2563EB", "#16A34A", "#9333EA", "#DB2777", "#0891B2", "#CA8A04", "#DC2626", "#4F46E5"];
/** Stable colour slot (0-7) per person/tab; CSS classes .presence-c0 … .presence-c7. */
export function colorIndex(key: string): number {
  let h = 0;
  for (const ch of key) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h % PRESENCE_COLORS.length;
}
