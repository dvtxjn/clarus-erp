"""
Check the Google Drive setup before switching STORAGE_BACKEND=drive.

    .venv/bin/python scripts/check_drive.py

Reads backend/.env. Checks: the key loads and can log in; each of the three folders
is reachable; the Documents folder accepts a new folder ("_erp-connection-check",
created once and reused — nothing is ever deleted); a delete is refused by the code.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app.storage import roots  # noqa: E402
from app.storage.drive_client import API, DriveClient, DriveError, load_service_account  # noqa: E402


def main() -> int:
    ok = True
    try:
        sa = load_service_account()
        print(f"key: {sa['client_email']}")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL key: {e}")
        return 1
    r = roots()
    missing = [k for k, v in r.items() if not v]
    if missing:
        print(f"FAIL folder ids not set: {', '.join(missing)}")
        return 1
    client = DriveClient(r.values(), service_account=sa)
    for name, fid in r.items():
        try:
            meta = client.get(fid, "id,name,driveId,capabilities(canAddChildren,canDelete,canTrash)")
            caps = meta.get("capabilities", {})
            print(f"ok   {name}: '{meta['name']}' (shared drive: {'yes' if meta.get('driveId') else 'NO'}) "
                  f"add={caps.get('canAddChildren')} delete={caps.get('canDelete')} trash={caps.get('canTrash')}")
            if caps.get("canDelete") or caps.get("canTrash"):
                print("     WARNING: the service account could delete here — make it a Contributor, not a Content manager")
                ok = False
        except DriveError as e:
            print(f"FAIL {name}: {e}")
            ok = False
    try:
        fid = client.find_folder(r["Documents"], "_erp-connection-check") or \
            client.create_folder(r["Documents"], "_erp-connection-check")
        print(f"ok   can save in Documents (folder {fid})")
    except DriveError as e:
        print(f"FAIL saving in Documents: {e}")
        ok = False
    try:
        client._req("DELETE", f"{API}/files/none")
        ok = False
    except DriveError:
        print("ok   deletes are refused by the ERP")
    print("\nAll good — set STORAGE_BACKEND=drive and restart." if ok else "\nFix the FAIL/WARNING lines first.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
