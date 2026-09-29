import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import type { ShipmentDocument } from "./types";

/**
 * Documents are added in the background (client, 2026-09-29): pick or upload, then carry on
 * working anywhere in the app — a small tray shows progress. Up to 3 files are processed at
 * once (each is downloaded / read / applied by the server). The queue lives as long as the
 * tab: closing the tab while files are still being added asks first.
 */
export interface UploadJob {
  id: string;
  shipmentId: number;
  shipmentLabel: string;
  fileName: string;
  typeLabel: string;
  status: "queued" | "running" | "done" | "error";
  error?: string;
  doc?: ShipmentDocument;
  showResult?: boolean; // single upload: show the "what was read" banner when done
}
type NewJob = Omit<UploadJob, "id" | "status" | "error" | "doc"> & { run: () => Promise<ShipmentDocument> };

interface QueueApi {
  jobs: UploadJob[];
  enqueue: (jobs: NewJob[]) => void;
  onFinished: (cb: (job: UploadJob) => void) => () => void;
}
const QueueContext = createContext<QueueApi | null>(null);
const PARALLEL = 3;

function errorText(e: unknown): string {
  const detail = axios.isAxiosError(e) ? e.response?.data?.detail : null;
  return typeof detail === "string" ? detail : "Couldn't add this file";
}

export function UploadQueueProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<UploadJob[]>([]);
  const runs = useRef(new Map<string, () => Promise<ShipmentDocument>>());
  const running = useRef(0);
  const listeners = useRef(new Set<(job: UploadJob) => void>());
  const jobsRef = useRef<UploadJob[]>([]);
  jobsRef.current = jobs;

  const update = (id: string, patch: Partial<UploadJob>) =>
    setJobs((prev) => prev.map((j) => (j.id === id ? { ...j, ...patch } : j)));

  const pump = useCallback(() => {
    while (running.current < PARALLEL) {
      const next = jobsRef.current.find((j) => j.status === "queued" && runs.current.has(j.id));
      if (!next) return;
      const run = runs.current.get(next.id)!;
      runs.current.delete(next.id);
      running.current += 1;
      jobsRef.current = jobsRef.current.map((j) => (j.id === next.id ? { ...j, status: "running" } : j));
      update(next.id, { status: "running" });
      run()
        .then((doc) => {
          const done = { ...next, status: "done" as const, doc };
          update(next.id, { status: "done", doc });
          listeners.current.forEach((cb) => cb(done));
        })
        .catch((e) => {
          const failed = { ...next, status: "error" as const, error: errorText(e) };
          update(next.id, { status: "error", error: failed.error });
          listeners.current.forEach((cb) => cb(failed));
        })
        .finally(() => {
          running.current -= 1;
          pump();
        });
    }
  }, []);

  const enqueue = useCallback(
    (newJobs: NewJob[]) => {
      const added = newJobs.map(({ run, ...j }) => {
        const id = Math.random().toString(36).slice(2);
        runs.current.set(id, run);
        return { ...j, id, status: "queued" as const };
      });
      jobsRef.current = [...jobsRef.current, ...added];
      setJobs(jobsRef.current);
      pump();
    },
    [pump],
  );

  const onFinished = useCallback((cb: (job: UploadJob) => void) => {
    listeners.current.add(cb);
    return () => {
      listeners.current.delete(cb);
    };
  }, []);

  const busy = jobs.some((j) => j.status === "queued" || j.status === "running");
  useEffect(() => {
    if (!busy) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = ""; // "Leave site? Documents are still being added"
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [busy]);

  return (
    <QueueContext.Provider value={{ jobs, enqueue, onFinished }}>
      {children}
      <UploadTray jobs={jobs} onClear={() => setJobs((prev) => prev.filter((j) => j.status === "queued" || j.status === "running"))} />
    </QueueContext.Provider>
  );
}

export function useUploadQueue(): QueueApi {
  const ctx = useContext(QueueContext);
  if (!ctx) throw new Error("useUploadQueue must be used inside <UploadQueueProvider>");
  return ctx;
}

const KIND_LABEL: Record<string, string> = { digital: "Digital", partly: "Partly scanned", scanned: "Scanned", unreadable: "Unreadable" };

function UploadTray({ jobs, onClear }: { jobs: UploadJob[]; onClear: () => void }) {
  const [open, setOpen] = useState(true);
  if (jobs.length === 0) return null;
  const done = jobs.filter((j) => j.status === "done").length;
  const failed = jobs.filter((j) => j.status === "error").length;
  const active = jobs.length - done - failed;
  return (
    <div className="upload-tray" role="status" aria-live="polite">
      <div className="upload-tray-head">
        <button type="button" className="link-btn" onClick={() => setOpen((o) => !o)}>
          {active > 0 ? `Adding documents — ${done + failed} of ${jobs.length} done` : `Documents added: ${done}`}
          {failed > 0 && ` · ${failed} failed`} {open ? "▾" : "▴"}
        </button>
        {active === 0 && (
          <button type="button" className="link-btn" onClick={onClear}>
            Clear
          </button>
        )}
      </div>
      {open && (
        <ul className="upload-tray-list">
          {jobs.map((j) => (
            <li key={j.id} className={`upload-job upload-job-${j.status}`}>
              <span className="upload-job-name" title={j.fileName}>
                {j.fileName}
              </span>
              <span className="upload-job-meta">
                {j.typeLabel} · <Link to={`/shipments/${j.shipmentId}`}>{j.shipmentLabel}</Link>
              </span>
              <span className="upload-job-status">
                {j.status === "queued" && "Waiting"}
                {j.status === "running" && "Adding…"}
                {j.status === "done" && `✓ ${j.doc?.pdf_kind ? KIND_LABEL[j.doc.pdf_kind] ?? "" : "Added"}`}
                {j.status === "error" && <span title={j.error}>Failed: {j.error}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
