"""
Drive through the server's own Google connection (service account), so staff never sign in
to Google or use the Google picker in the browser: find a shipment's folder by name.
Read only — nothing in Drive is created, moved or deleted here.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query

from app import storage
from app.core.deps import get_current_user
from app.models.user import User
from app.routers.drive_folder import _folder_pdfs
from app.storage.drive_client import DriveError

router = APIRouter(prefix="/drive", tags=["drive"])


def _client():
    client = storage.drive()
    if client is None:
        raise HTTPException(status_code=400, detail="The server has no Google Drive connection.")
    return client


@router.get("/status")
def drive_status(current_user: User = Depends(get_current_user)):
    """server=True: folders and files are found and read by the server (no Google sign-in)."""
    return {"server": storage.drive() is not None}


@router.get("/folders")
def search_folders(q: list[str] = Query(...), current_user: User = Depends(get_current_user)):
    """Folders whose name contains any of the q terms (e.g. the BL, or "JOB 129")."""
    client = _client()
    terms = [t.strip() for t in q if len(t.strip()) >= 3]
    if not terms:
        return []
    try:
        found = client.search_folders(terms)
    except DriveError:
        raise HTTPException(status_code=502, detail="Couldn't reach Google Drive — try again.")
    return [{"id": f["id"], "name": f.get("name", ""),
             "url": f.get("webViewLink") or f"https://drive.google.com/drive/folders/{f['id']}"} for f in found]


@router.get("/folders/{folder_id}/pdfs")
def folder_pdfs(folder_id: str, current_user: User = Depends(get_current_user)):
    """PDFs in a folder and its sub-folders (names only), to pick from."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{5,200}", folder_id):
        raise HTTPException(status_code=400, detail="That isn't a Google Drive folder id.")
    try:
        return [{"id": f["id"], "name": f["name"]} for f in _folder_pdfs(_client(), folder_id)]
    except DriveError:
        raise HTTPException(status_code=502, detail="Couldn't open that folder in Google Drive — check the ERP can see it.")
