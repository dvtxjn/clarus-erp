"""
ICEGATE public enquiry — Sea IGM, as plain JSON calls (the page's own; no browser). MBL + port code.
Same result shape as app/igm/icegate.lookup (the browser version, kept for reference / fallback).
"""
from datetime import datetime
from typing import Optional

import httpx

from app.igm.icd import HEADERS, _json

API = "https://foservices.icegate.gov.in/enquiry/"
NA = {"", "N.A.", "NA", "-"}


def _s(v: Optional[str]) -> Optional[str]:
    v = (v or "").strip()
    return None if v in NA else v


def _dmy(v: Optional[str]) -> Optional[str]:
    """ICEGATE mixes '2026-07-21 00:00:00.0', '24/08/2026', '24 AUG 2026 12:08' → '21-Jul-2026'."""
    v = _s(v)
    if not v:
        return None
    for fmt, cut in (("%Y-%m-%d", 10), ("%d/%m/%Y", 10), ("%d %b %Y", 11)):
        try:
            return datetime.strptime(v[:cut].title(), fmt).strftime("%d-%b-%Y")
        except ValueError:
            continue
    return v


def fetch(mbl: str, port: str, client: Optional[httpx.Client] = None) -> dict:
    own = client is None
    client = client or httpx.Client(timeout=30, headers=HEADERS)
    try:
        r = client.post(API + "enquiryatices/SeaIgmEnq", json={"location": port, "masterBlNo": mbl.strip()})
        r.raise_for_status()
        rows = _json(r)
        if not isinstance(rows, list) or not rows:
            return {"status": "IGM Not Filed"}
        bl = rows[0]
        out = {
            "status": "IGM Filed",
            "line_no": _s(bl.get("lineNo")), "sub_line_no": _s(bl.get("subLineNo")),
            "mbl_no": _s(bl.get("blNo")), "mbl_date": _dmy(bl.get("blDate")),
            "hbl_no": _s(bl.get("houseBlNo")), "hbl_date": _dmy(bl.get("houseBlDate")),
            "gross_weight": _s(bl.get("grossWeight")), "unit_weight": _s(bl.get("unitOfWeight")),
            "total_package": _s(bl.get("totalPackage")), "package_code": _s(bl.get("packageCode")),
            "cargo_movement": _s(bl.get("cargoMovement")), "port_dest": _s(bl.get("portDest")),
            "goods": _s(bl.get("descOfGoods")),
            "igm_no": _s(bl.get("igmNo")), "igm_date": _dmy(bl.get("igmDate")),
            "inw_date": None, "voyage_no": None, "vessel_code": None, "imo_no": None, "containers": [],
        }
        if out["igm_no"] and bl.get("igmDate"):
            m = client.post(API + "publicEnquiries/SeaIgmMorePublicDetails", json={
                "masterBlNo": mbl.strip(), "location": port, "igmNo": out["igm_no"], "igmDate": bl.get("igmDate")})
            if m.is_success and _json(m):
                x = _json(m)[0]
                out.update(inw_date=_dmy(x.get("inwardDate")), voyage_no=_s(x.get("voyageNo")),
                           vessel_code=_s(x.get("vesselCode")), imo_no=_s(x.get("imoNo")))
            c = client.post(API + "publicEnquiries/SeaIgmContPublicDetails", json={
                "lineNo": bl.get("lineNo"), "subLineNo": bl.get("subLineNo"), "igmNo": out["igm_no"], "location": port})
            if c.is_success:
                out["containers"] = [{"container": _s(y.get("contDetails")), "status": _s(y.get("contStatus"))}
                                     for y in _json(c) if _s(y.get("contDetails"))]
        return out
    finally:
        if own:
            client.close()
