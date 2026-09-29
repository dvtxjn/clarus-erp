import type { Shipment } from "./types";

/**
 * Which Drive folder is a shipment's? Staff name them "JOB <job number> - <MBL or HBL>"
 * (client, 2026-09-29). A folder is:
 *   verified  — its name has the shipment's MBL/HBL AND the right job number → linked automatically
 *   no-job    — has the MBL/HBL but no job number in the name            → suggested
 *   job-differs — has the MBL/HBL but a different job number              → suggested, flagged
 *   job-only  — the right job number but not the MBL/HBL                  → suggested, flagged
 */
export type FolderMatch = "verified" | "no-job" | "job-differs" | "job-only";

export interface DriveFolderHit {
  id: string;
  name: string;
  url: string;
}

const norm = (s: string | null | undefined) => (s ?? "").toUpperCase().replace(/[^A-Z0-9]/g, "");

/** "JOB 129 - CSX26JEDNSA021814" -> { job: "129", ref: "CSX26JEDNSA021814" } */
export function parseFolderName(name: string): { job: string | null; ref: string } {
  const m = name.match(/^\s*JOB\s*(?:NO\.?)?\s*[-#:]?\s*(\d+)\s*[-–—_:]?\s*(.*)$/i);
  return m ? { job: m[1], ref: m[2] } : { job: null, ref: name };
}

/** MBL / HBL values to look for (an old "MBL/HBL" cell is split at the slash). */
export function shipmentRefs(s: Pick<Shipment, "mbl" | "hbl">): string[] {
  const raw = [s.mbl, s.hbl, ...(s.mbl ?? "").split("/")].map((r) => (r ?? "").trim());
  return [...new Set(raw.filter((r) => norm(r).length >= 5))];
}

export function matchFolder(s: Pick<Shipment, "mbl" | "hbl" | "job">, folderName: string): FolderMatch | null {
  const { job, ref } = parseFolderName(folderName);
  const refHit = shipmentRefs(s).some((r) => norm(ref).includes(norm(r)) || norm(folderName).includes(norm(r)));
  const myJob = (s.job ?? "").trim();
  const jobHit = !!job && !!myJob && Number(job) === Number(myJob);
  if (refHit && jobHit) return "verified";
  if (refHit) return job && myJob ? "job-differs" : "no-job";
  if (jobHit) return "job-only";
  return null;
}

export const MATCH_LABELS: Record<FolderMatch, string> = {
  verified: "Job and MBL/HBL match",
  "no-job": "MBL/HBL matches (no job number in the name)",
  "job-differs": "MBL/HBL matches but the job number is different",
  "job-only": "Job number matches but not the MBL/HBL",
};

export interface FolderResult {
  auto: DriveFolderHit | null; // exactly one verified folder -> safe to link
  candidates: { folder: DriveFolderHit; match: FolderMatch }[];
}

export function pickFolder(s: Pick<Shipment, "mbl" | "hbl" | "job">, hits: DriveFolderHit[]): FolderResult {
  const order: FolderMatch[] = ["verified", "no-job", "job-differs", "job-only"];
  const candidates = hits
    .map((folder) => ({ folder, match: matchFolder(s, folder.name) }))
    .filter((c): c is { folder: DriveFolderHit; match: FolderMatch } => c.match !== null)
    .sort((a, b) => order.indexOf(a.match) - order.indexOf(b.match));
  const verified = candidates.filter((c) => c.match === "verified");
  return { auto: verified.length === 1 ? verified[0].folder : null, candidates };
}

