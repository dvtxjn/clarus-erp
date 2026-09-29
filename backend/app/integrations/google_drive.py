"""
Fetch a PDF the user picked in Google Drive (Google Picker in the browser).

The browser sends the picked file's id plus the user's short-lived OAuth
access token (scope drive.file = only files the user explicitly picked).
The token is used for these two requests and never stored.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

DRIVE_API = "https://www.googleapis.com/drive/v3/files"
MAX_BYTES = 25 * 1024 * 1024
_FILE_ID = re.compile(r"^[A-Za-z0-9_-]{10,200}$")


class DriveError(Exception):
    """Message is safe to show to the user."""


@dataclass
class DriveFile:
    file_id: str
    name: str
    web_link: str | None
    content: bytes


async def fetch_drive_pdf(file_id: str, access_token: str) -> DriveFile:
    if not _FILE_ID.match(file_id):
        raise DriveError("That doesn't look like a Google Drive file id.")
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"supportsAllDrives": "true"}
    async with httpx.AsyncClient(timeout=60) as client:
        meta = await client.get(f"{DRIVE_API}/{file_id}", headers=headers,
                                params={**params, "fields": "id,name,mimeType,size,webViewLink"})
        if meta.status_code in (401, 403):
            raise DriveError("Google Drive refused access — sign in again and re-pick the file.")
        if meta.status_code == 404:
            raise DriveError("File not found in Google Drive (or you don't have access to it).")
        meta.raise_for_status()
        info = meta.json()
        if info.get("mimeType") != "application/pdf":
            raise DriveError(f"'{info.get('name')}' isn't a PDF — pick the PDF copy of the document.")
        if int(info.get("size") or 0) > MAX_BYTES:
            raise DriveError(f"'{info.get('name')}' is larger than 25 MB.")
        data = await client.get(f"{DRIVE_API}/{file_id}", headers=headers, params={**params, "alt": "media"})
        data.raise_for_status()
        if len(data.content) > MAX_BYTES:
            raise DriveError(f"'{info.get('name')}' is larger than 25 MB.")
    return DriveFile(file_id=file_id, name=info.get("name") or "drive.pdf",
                     web_link=info.get("webViewLink"), content=data.content)


UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"


async def upload_pdf(folder_id: str, name: str, content: bytes, access_token: str) -> tuple[str, str | None]:
    """Save a PDF into a Drive folder. Returns (file id, web link).
    With the drive.file scope this works for folders the user linked through
    the Drive picker (a pasted folder link alone doesn't grant access)."""
    if not _FILE_ID.match(folder_id):
        raise DriveError("The linked Drive folder id isn't valid — link the folder again.")
    metadata = {"name": name, "parents": [folder_id], "mimeType": "application/pdf"}
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            UPLOAD_API,
            params={"uploadType": "multipart", "supportsAllDrives": "true", "fields": "id,webViewLink"},
            headers={"Authorization": f"Bearer {access_token}"},
            files={
                "metadata": (None, json.dumps(metadata), "application/json; charset=UTF-8"),
                "file": (name, content, "application/pdf"),
            },
        )
    if r.status_code in (401, 403, 404):
        raise DriveError("Couldn't save into the shipment's Drive folder — re-link the folder "
                         "with 'Choose folder' (a pasted link doesn't give the app access).")
    r.raise_for_status()
    info = r.json()
    return info["id"], info.get("webViewLink")
