import { useEffect, useState } from "react";
import { API_BASE_URL } from "./api";

/** Is this the sandbox copy (P4)? From the public /health endpoint; with its demo login. */
export interface SandboxInfo {
  sandbox: boolean;
  demo_email?: string;
  demo_password?: string;
}

let cached: Promise<SandboxInfo> | null = null;

export function useSandbox(): SandboxInfo {
  const [info, setInfo] = useState<SandboxInfo>({ sandbox: false });
  useEffect(() => {
    cached ??= fetch(`${API_BASE_URL}/health`, { headers: { Accept: "application/json" } })
      .then((r) => r.json())
      .catch(() => ({ sandbox: false }));
    cached.then(setInfo);
  }, []);
  return info;
}
