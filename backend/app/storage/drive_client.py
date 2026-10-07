"""
Minimal Google Drive v3 client for the server (service account, Shared Drive).

Client rule (2026-09-29): the ERP can only READ and SAVE in Google Drive — NO DELETION.
  - The service account is a *Contributor* on the Shared Drive (can add and edit, cannot
    delete, trash or move) — Google itself refuses deletes.
  - This client has no delete / trash / move method, and _req refuses DELETE requests and
    any body that sets "trashed". A removed document is only renamed "[removed] …".
Safety guard: every write names a folder, and it must sit inside one of the configured
root folders (Documents / Invoices / Backups); anything else is refused before a request.
"""
from __future__ import annotations

import json
import os
import time
from typing import Iterable, Optional

import httpx
from jose import jwt

API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHARED = {"supportsAllDrives": "true"}


class DriveError(Exception):
    pass


class OutsideRoot(DriveError):
    """A write aimed at a folder outside the configured roots."""


def load_service_account() -> dict:
    """GOOGLE_SERVICE_ACCOUNT_JSON: the key's JSON text, or a path to the .json file."""
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise DriveError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")
    if raw.startswith("{"):
        return json.loads(raw)
    with open(raw) as f:
        return json.load(f)


class DriveClient:
    def __init__(self, roots: Iterable[str], service_account: Optional[dict] = None, timeout: float = 60):
        self.roots = {r for r in roots if r}
        if not self.roots:
            raise DriveError("No Drive root folders configured")
        self._sa = service_account
        self._token: Optional[str] = None
        self._token_exp = 0.0
        self._inside: set[str] = set(self.roots)  # folders already proven to be inside a root
        self._http = httpx.Client(timeout=timeout)

    # --- auth: service account -> short-lived access token ---
    def _auth(self) -> dict:
        if not self._token or time.time() > self._token_exp - 60:
            sa = self._sa or load_service_account()
            now = int(time.time())
            assertion = jwt.encode(
                {"iss": sa["client_email"], "scope": "https://www.googleapis.com/auth/drive",
                 "aud": sa.get("token_uri", "https://oauth2.googleapis.com/token"), "iat": now, "exp": now + 3600},
                sa["private_key"], algorithm="RS256")
            r = self._http.post(sa.get("token_uri", "https://oauth2.googleapis.com/token"),
                                data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                      "assertion": assertion})
            if r.status_code != 200:
                raise DriveError(f"Google login for the service account failed ({r.status_code})")
            body = r.json()
            self._token, self._token_exp = body["access_token"], time.time() + body.get("expires_in", 3600)
        return {"Authorization": f"Bearer {self._token}"}

    def _req(self, method: str, url: str, **kw) -> httpx.Response:
        if method.upper() == "DELETE" or "trashed" in json.dumps(kw.get("json") or {}):
            raise DriveError("Refused: the ERP never deletes or trashes anything in Google Drive")
        params = {**SHARED, **kw.pop("params", {})}
        r = self._http.request(method, url, params=params, headers=self._auth(), **kw)
        if r.status_code >= 400:
            raise DriveError(f"Drive {method} {url.rsplit('/', 1)[-1]}: {r.status_code} {r.text[:200]}")
        return r

    # --- guard ---
    def check_inside(self, folder_id: str) -> None:
        """Walk up the parents until a root is reached; refuse otherwise."""
        seen, fid = [], folder_id
        for _ in range(12):
            if fid in self._inside:
                self._inside.update(seen)
                return
            seen.append(fid)
            meta = self._req("GET", f"{API}/files/{fid}", params={"fields": "id,parents"}).json()
            parents = meta.get("parents") or []
            if not parents:
                break
            fid = parents[0]
        raise OutsideRoot(f"Refused: folder {folder_id} is not inside the ERP's Drive folders")

    # --- reads ---
    def get(self, file_id: str, fields: str = "id,name,parents,webViewLink,size,md5Checksum") -> dict:
        return self._req("GET", f"{API}/files/{file_id}", params={"fields": fields}).json()

    def find_folder(self, parent_id: str, name: str) -> Optional[str]:
        safe = name.replace("\\", "\\\\").replace("'", "\\'")
        r = self._req("GET", f"{API}/files", params={
            "q": f"'{parent_id}' in parents and name = '{safe}' and mimeType = '{FOLDER_MIME}' and trashed = false",
            "fields": "files(id)", "includeItemsFromAllDrives": "true", "corpora": "allDrives", "pageSize": "10"})
        files = r.json().get("files", [])
        return files[0]["id"] if files else None

    def list_children(self, folder_id: str) -> list[dict]:
        """Files and folders directly inside a folder (read only)."""
        out, token = [], None
        while True:
            params = {"q": f"'{folder_id}' in parents and trashed = false", "fields": "nextPageToken, files(id,name,mimeType,size,md5Checksum)",
                      "includeItemsFromAllDrives": "true", "corpora": "allDrives", "pageSize": "200"}
            if token:
                params["pageToken"] = token
            body = self._req("GET", f"{API}/files", params=params).json()
            out += body.get("files", [])
            token = body.get("nextPageToken")
            if not token:
                return out

    def download(self, file_id: str) -> bytes:
        return self._req("GET", f"{API}/files/{file_id}", params={"alt": "media"}).content

    # --- writes (all guarded) ---
    def create_folder(self, parent_id: str, name: str) -> str:
        self.check_inside(parent_id)
        r = self._req("POST", f"{API}/files", params={"fields": "id"},
                      json={"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]})
        fid = r.json()["id"]
        self._inside.add(fid)
        return fid

    def upload(self, parent_id: str, name: str, data: bytes, mime: str = "application/pdf",
               linked: bool = False) -> dict:
        """Save a new file (never overwrites: Drive keeps same-named files side by side).
        linked=True: a shipment folder staff linked (or picked at save time) — it may sit outside the roots."""
        if not linked:
            self.check_inside(parent_id)
        boundary = "erp-upload-boundary"
        meta = json.dumps({"name": name, "parents": [parent_id]})
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
                f"--{boundary}\r\nContent-Type: {mime}\r\n\r\n").encode() + data + f"\r\n--{boundary}--".encode()
        r = self._http.post(f"{UPLOAD}/files",
                            params={**SHARED, "uploadType": "multipart", "fields": "id,webViewLink,size,md5Checksum"},
                            content=body,
                            headers={**self._auth(), "Content-Type": f"multipart/related; boundary={boundary}"})
        if r.status_code >= 400:
            raise DriveError(f"Drive upload: {r.status_code} {r.text[:200]}")
        return r.json()

    def rename(self, file_id: str, new_name: str, linked: bool = False) -> None:
        """Only the name changes (e.g. "[removed] …"); the file stays where it is.
        linked=True: a file the ERP itself saved into a shipment's linked folder."""
        parents = self.get(file_id, "parents").get("parents") or []
        if not parents:
            raise OutsideRoot("Refused: file has no parent folder")
        if not linked:
            self.check_inside(parents[0])
        self._req("PATCH", f"{API}/files/{file_id}", params={"fields": "id"}, json={"name": new_name})
