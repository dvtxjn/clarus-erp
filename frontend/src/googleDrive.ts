import { pickFolder, shipmentRefs, type FolderResult } from "./folderMatch";
import type { Shipment } from "./types";

/**
 * "Choose from Google Drive": Google Picker + a drive.file OAuth token.
 * drive.file means the app can only open the files the user picks — not
 * browse or change anything else in their Drive.
 *
 * Needs (frontend .env): VITE_GOOGLE_CLIENT_ID, VITE_GOOGLE_API_KEY,
 * VITE_GOOGLE_APP_ID (Google Cloud project number). See PROGRESS.md.
 */
const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined;
const API_KEY = import.meta.env.VITE_GOOGLE_API_KEY as string | undefined;
const APP_ID = import.meta.env.VITE_GOOGLE_APP_ID as string | undefined;
// drive.file: open only the files the user picks. drive.metadata.readonly: see file and
// folder NAMES (to find "JOB 129 - <MBL>" folders) — read-only, can't open or change anything.
const SCOPE = "https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.metadata.readonly";

export const driveConfigured = Boolean(CLIENT_ID && API_KEY && APP_ID);

export interface PickedDriveFile {
  id: string;
  name: string;
  accessToken: string;
}

/* eslint-disable @typescript-eslint/no-explicit-any */
type GoogleGlobal = any;
declare global {
  interface Window {
    gapi?: GoogleGlobal;
    google?: GoogleGlobal;
  }
}

const loaded = new Map<string, Promise<void>>();
function loadScript(src: string): Promise<void> {
  if (!loaded.has(src)) {
    loaded.set(
      src,
      new Promise((resolve, reject) => {
        const el = document.createElement("script");
        el.src = src;
        el.async = true;
        el.onload = () => resolve();
        el.onerror = () => reject(new Error(`Couldn't load ${src}`));
        document.head.appendChild(el);
      }),
    );
  }
  return loaded.get(src)!;
}

let pickerReady: Promise<void> | null = null;
function loadPicker(): Promise<void> {
  pickerReady ??= Promise.all([
    loadScript("https://apis.google.com/js/api.js"),
    loadScript("https://accounts.google.com/gsi/client"),
  ]).then(() => new Promise<void>((resolve) => window.gapi.load("picker", () => resolve())));
  return pickerReady;
}

const TOKEN_KEY = "googleDrive.token";
let cachedToken: { token: string; expires: number } | null = (() => {
  try {
    return JSON.parse(sessionStorage.getItem(TOKEN_KEY) || "null");
  } catch {
    return null;
  }
})();
function saveToken(t: typeof cachedToken) {
  cachedToken = t;
  try {
    if (t) sessionStorage.setItem(TOKEN_KEY, JSON.stringify(t));
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private window: keep it in memory only */
  }
}
/** Google access token (drive.file); asks the user to sign in if needed. */
export async function getDriveToken(): Promise<string> {
  if (!driveConfigured) throw new Error("Google Drive isn't set up yet.");
  await loadPicker();
  return getToken();
}
let needConsent = false;
function getToken(): Promise<string> {
  if (cachedToken && cachedToken.expires > Date.now() + 60_000) return Promise.resolve(cachedToken.token);
  return new Promise((resolve, reject) => {
    const client = window.google.accounts.oauth2.initTokenClient({
      client_id: CLIENT_ID,
      scope: SCOPE,
      callback: (resp: { access_token?: string; expires_in?: number; error?: string }) => {
        if (!resp.access_token) return reject(new Error(resp.error || "Google sign-in was cancelled."));
        saveToken({ token: resp.access_token, expires: Date.now() + (resp.expires_in ?? 3600) * 1000 });
        resolve(resp.access_token);
      },
      error_callback: () => reject(new Error("Google sign-in was cancelled.")),
    });
    // "" = Google asks only the first time; after that it reconnects without the "continue" screen
    client.requestAccessToken({ prompt: needConsent ? "consent" : "" });
    needConsent = false;
  });
}

/** Folders anywhere in the user's Drive / Shared Drives whose name contains any of `terms`. */
export async function searchDriveFolders(terms: string[]): Promise<{ id: string; name: string; url: string }[]> {
  const wanted = terms.map((t) => t.trim()).filter(Boolean);
  if (!wanted.length) return [];
  const token = await getDriveToken();
  const esc = (t: string) => t.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
  const q = `mimeType = 'application/vnd.google-apps.folder' and trashed = false and (${wanted
    .map((t) => `name contains '${esc(t)}'`)
    .join(" or ")})`;
  const params = new URLSearchParams({
    q,
    fields: "files(id,name,webViewLink)",
    pageSize: "50",
    supportsAllDrives: "true",
    includeItemsFromAllDrives: "true",
    corpora: "allDrives",
  });
  const res = await fetch(`https://www.googleapis.com/drive/v3/files?${params}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 401 || res.status === 403) {
    saveToken(null); // e.g. signed in before folder search was added: ask again
    needConsent = true;
    throw new Error("Google needs you to allow folder search — click again and accept.");
  }
  if (!res.ok) throw new Error(`Google Drive search failed (${res.status})`);
  const body = (await res.json()) as { files?: { id: string; name: string; webViewLink?: string }[] };
  return (body.files ?? []).map((f) => ({
    id: f.id,
    name: f.name,
    url: f.webViewLink ?? `https://drive.google.com/drive/folders/${f.id}`,
  }));
}

/** Opens the Google Drive picker (PDFs only), starting in `startFolderId` if given. Resolves null if cancelled. */
export async function pickPdfFromDrive(startFolderId?: string | null): Promise<PickedDriveFile | null> {
  if (!driveConfigured) throw new Error("Google Drive isn't set up yet.");
  await loadPicker();
  const accessToken = await getToken();
  const g = window.google.picker;
  return new Promise((resolve) => {
    const myDrive = new g.DocsView(g.ViewId.DOCS).setMimeTypes("application/pdf").setIncludeFolders(true);
    if (startFolderId) myDrive.setParent(startFolderId);
    const sharedDrives = new g.DocsView(g.ViewId.DOCS)
      .setMimeTypes("application/pdf")
      .setIncludeFolders(true)
      .setEnableDrives(true);
    const picker = new g.PickerBuilder()
      .enableFeature(g.Feature.SUPPORT_DRIVES)
      .addView(myDrive)
      .addView(sharedDrives)
      .setOAuthToken(accessToken)
      .setDeveloperKey(API_KEY)
      .setAppId(APP_ID)
      .setTitle("Choose the PDF")
      .setCallback((data: { action: string; docs?: { id: string; name: string }[] }) => {
        if (data.action === g.Action.PICKED && data.docs?.[0]) {
          resolve({ id: data.docs[0].id, name: data.docs[0].name, accessToken });
        } else if (data.action === g.Action.CANCEL) {
          resolve(null);
        }
      })
      .build();
    picker.setVisible(true);
  });
}

/** Several PDFs at once from the shipment's folder (staff-made). Resolves null if cancelled. */
export async function pickPdfsFromFolder(
  folderId: string,
): Promise<{ files: { id: string; name: string }[]; accessToken: string } | null> {
  if (!driveConfigured) throw new Error("Google Drive isn't set up yet.");
  await loadPicker();
  const accessToken = await getToken();
  const g = window.google.picker;
  return new Promise((resolve) => {
    const inFolder = new g.DocsView(g.ViewId.DOCS)
      .setMimeTypes("application/pdf")
      .setIncludeFolders(true) // staff sometimes keep sub-folders
      .setParent(folderId);
    new g.PickerBuilder()
      .enableFeature(g.Feature.SUPPORT_DRIVES)
      .enableFeature(g.Feature.MULTISELECT_ENABLED)
      .addView(inFolder)
      .setOAuthToken(accessToken)
      .setDeveloperKey(API_KEY)
      .setAppId(APP_ID)
      .setTitle("Select the shipment's files (you can pick several)")
      .setCallback((data: { action: string; docs?: { id: string; name: string }[] }) => {
        if (data.action === g.Action.PICKED && data.docs?.length) {
          resolve({ files: data.docs.map((d) => ({ id: d.id, name: d.name })), accessToken });
        } else if (data.action === g.Action.CANCEL) {
          resolve(null);
        }
      })
      .build()
      .setVisible(true);
  });
}

export interface PickedDriveFolder {
  id: string;
  name: string;
  url: string | null;
}

/** Folder picker. Picking a folder is what lets the app save files into it. */
export async function pickDriveFolder(): Promise<PickedDriveFolder | null> {
  if (!driveConfigured) throw new Error("Google Drive isn't set up yet.");
  await loadPicker();
  const accessToken = await getToken();
  const g = window.google.picker;
  return new Promise((resolve) => {
    const folders = new g.DocsView(g.ViewId.FOLDERS)
      .setIncludeFolders(true)
      .setSelectFolderEnabled(true)
      .setMimeTypes("application/vnd.google-apps.folder");
    const sharedFolders = new g.DocsView(g.ViewId.FOLDERS)
      .setIncludeFolders(true)
      .setSelectFolderEnabled(true)
      .setEnableDrives(true)
      .setMimeTypes("application/vnd.google-apps.folder");
    new g.PickerBuilder()
      .enableFeature(g.Feature.SUPPORT_DRIVES)
      .addView(folders)
      .addView(sharedFolders)
      .setOAuthToken(accessToken)
      .setDeveloperKey(API_KEY)
      .setAppId(APP_ID)
      .setTitle("Choose this shipment's folder")
      .setCallback((data: { action: string; docs?: { id: string; name: string; url?: string }[] }) => {
        if (data.action === g.Action.PICKED && data.docs?.[0]) {
          const d = data.docs[0];
          resolve({ id: d.id, name: d.name, url: d.url ?? `https://drive.google.com/drive/folders/${d.id}` });
        } else if (data.action === g.Action.CANCEL) {
          resolve(null);
        }
      })
      .build()
      .setVisible(true);
  });
}

/** Folder id from a pasted Drive folder link (or a bare id). */
export function folderIdFromLink(input: string): string | null {
  const v = input.trim();
  const m = v.match(/\/folders\/([A-Za-z0-9_-]{10,})/) || v.match(/[?&]id=([A-Za-z0-9_-]{10,})/);
  if (m) return m[1];
  return /^[A-Za-z0-9_-]{10,200}$/.test(v) ? v : null;
}

/** Search Drive for a shipment's "JOB <job> - <MBL/HBL>" folder and rank the hits (folderMatch.ts). */
export async function findFolderFor(s: Pick<Shipment, "mbl" | "hbl" | "job">): Promise<FolderResult> {
  const terms = [...shipmentRefs(s), ...(s.job?.trim() ? [`JOB ${s.job.trim()}`] : [])];
  return pickFolder(s, await searchDriveFolders(terms));
}
