"""
ICEGATE public enquiry — ICD BL status (client, 2026-09-30): inland shipments (Panipat, Garhi, Sonepat…).
Only the MBL is needed. Two plain JSON calls (the page's own), no browser:
- publicblstatus-action {mawbNumber} → the BL at the ICD: gateway IGM no/date, line, gateway port,
  inward at the gateway, SMTP (rail permit) no/date, packages, weight
- publicblContainer-no-detail → the containers, each with its arrival date / status at the ICD
Read-only. ICEGATE error codes are ignored (client).
"""
from datetime import date, datetime
from typing import Optional

import httpx

API = "https://foservices.icegate.gov.in/enquiry/publicEnquiries/"
HEADERS = {
    "channel": "browser",
    "content-type": "application/json",
    "accept": "application/json, text/plain, */*",
    "origin": "https://foservices.icegate.gov.in",
    "referer": "https://foservices.icegate.gov.in/",
    "user-agent": "Mozilla/5.0 (Clarus ERP)",
}
NA = {"", "N.A.", "NA", "-"}


def _d(v: Optional[str]) -> Optional[date]:
    """ICEGATE writes '21 SEP 2026'."""
    v = (v or "").strip()
    if v in NA:
        return None
    for fmt in ("%d %b %Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(v.title(), fmt).date()
        except ValueError:
            continue
    return None


def _s(v: Optional[str]) -> Optional[str]:
    v = (v or "").strip()
    return None if v in NA else v


def fetch(mbl: str, client: Optional[httpx.Client] = None) -> dict:
    """{"found": False} or the BL(s) with their containers (duplicates merged, earliest arrival kept)."""
    own = client is None
    client = client or httpx.Client(timeout=30, headers=HEADERS)
    try:
        r = client.post(API + "publicblstatus-action", json={"mawbNumber": mbl.strip()})
        r.raise_for_status()
        rows = r.json() or []
        if not isinstance(rows, list) or not rows:
            return {"found": False}
        bls, containers = [], {}
        for x in rows:
            bls.append({
                "igm_no": _s(x.get("igmRTN")), "igm_date": _d(x.get("igmDT")), "line_no": _s(x.get("lineNo")),
                "icd": _s(x.get("portDest")), "gateway_port": _s(x.get("portREP")), "inward_date": _d(x.get("inwDT")),
                "smtp_no": _s(x.get("smtpNo")), "smtp_date": _d(x.get("smtpDT")),
                "total_package": _s(x.get("totalPackage")), "package_code": _s(x.get("packageCode")),
                "gross_weight": _s(x.get("grossWeight")), "unit": _s(x.get("uqc")),
            })
            c = client.post(API + "publicblContainer-no-detail", json={
                "subLineNo": x.get("subLineNo"), "igmRTN": x.get("igmRTN"), "igmDT": x.get("igmDT"),
                "customerSite": x.get("fileName"), "lineNo": x.get("lineNo"),
            })
            c.raise_for_status()
            for y in c.json() or []:
                no = _s(y.get("contNo"))
                if not no:
                    continue
                arrived = _d(y.get("arrDT"))
                seen = containers.get(no)
                if seen is None or (arrived and (seen["arrival_date"] is None or arrived < seen["arrival_date"])):
                    containers[no] = {"container_no": no, "status": _s(y.get("contStatus")),
                                      "arrival_date": arrived, "arrival_status": _s(y.get("arrStatus"))}
        return {"found": True, "bls": bls, "containers": list(containers.values())}
    finally:
        if own:
            client.close()
