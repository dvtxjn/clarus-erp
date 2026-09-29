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
const SCOPE = "https://www.googleapis.com/auth/drive.file";

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

let cachedToken: { token: string; expires: number } | null = null;
/** Google access token (drive.file); asks the user to sign in if needed. */
export async function getDriveToken(): Promise<string> {
  if (!driveConfigured) throw new Error("Google Drive isn't set up yet.");
  await loadPicker();
  return getToken();
}
function getToken(): Promise<string> {
  if (cachedToken && cachedToken.expires > Date.now() + 60_000) return Promise.resolve(cachedToken.token);
  return new Promise((resolve, reject) => {
    const client = window.google.accounts.oauth2.initTokenClient({
      client_id: CLIENT_ID,
      scope: SCOPE,
      callback: (resp: { access_token?: string; expires_in?: number; error?: string }) => {
        if (!resp.access_token) return reject(new Error(resp.error || "Google sign-in was cancelled."));
        cachedToken = { token: resp.access_token, expires: Date.now() + (resp.expires_in ?? 3600) * 1000 };
        resolve(resp.access_token);
      },
      error_callback: () => reject(new Error("Google sign-in was cancelled.")),
    });
    client.requestAccessToken({ prompt: cachedToken ? "" : "consent" });
  });
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
