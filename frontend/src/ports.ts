import { useEffect, useState } from "react";
import { listPorts } from "./api";
import type { Port } from "./types";

let cache: Port[] | null = null;

/** Port code -> name lookup, fetched once per page load. */
export function usePorts(): Port[] {
  const [ports, setPorts] = useState<Port[]>(cache ?? []);
  useEffect(() => {
    if (cache) return;
    listPorts().then((p) => {
      cache = p;
      setPorts(p);
    });
  }, []);
  return ports;
}

/** "INMUN1" -> "INMUN1 · Mundra" (falls back to the bare code). */
export function formatPort(code: string | null | undefined, ports: Port[]): string {
  if (!code) return "";
  const name = ports.find((p) => p.code === code)?.name;
  return name ? `${code} · ${name}` : code;
}
