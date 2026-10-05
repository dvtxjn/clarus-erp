"""
Which shipping line a BL belongs to, from the number's format (client's rules, 2026-09-30 — near-perfect on
our shipments), and the container number format.

Worked out on the fly (never stored), so a fresh tracker CSV import can't undo it. It also flags BL numbers
ICEGATE won't find as typed: HMM MBLs without their HDMU prefix, and HBLs sitting in the MBL column.
"""
import re
from typing import Optional

# (pattern, line, note) — first match wins. Client-confirmed first; the rest are the lines' public
# SCAC-style prefixes (marked), useful when a new line turns up.
RULES: list[tuple[str, str, Optional[str]]] = [
    (r"^\d{9}$", "Maersk", None),                      # Maersk BL: 9 characters, all digits
    (r"^HDMU", "HMM", None),
    (r"^BHMA", "HMM", "HMM MBL without its HDMU prefix — looked up on ICEGATE as HDMU{mbl}"),
    (r"^ACLJ", "NAVIO", None),
    (r"^CJHR", "Chartering RORO", "this is an HBL (Chartering RORO), not the MBL — ICEGATE's sea IGM needs the MBL"),
    (r"^OOLU", "OOCL", None),
    (r"^LPL", "CMA CGM", None),
    (r"^NAM", "CMA CGM", None),
    (r"^CYP", "CMA CGM", None),
    (r"^CSX", "Cordelia", None),
    (r"^HLCU", "Hapag-Lloyd", None),
    (r"^ONEY", "ONE", None),
    # public prefixes (not yet seen in our shipments)
    (r"^(MAEU|MRKU|MSKU)", "Maersk", None),
    (r"^(CMDU|CMAU)", "CMA CGM", None),
    (r"^MEDU", "MSC", None),
    (r"^COSU", "COSCO", None),
    (r"^EGLV", "Evergreen", None),
    (r"^ZIMU", "ZIM", None),
    (r"^YMLU", "Yang Ming", None),
]


def standard_mbl(bl: Optional[str]) -> Optional[str]:
    """The MBL as stored: HMM MBLs always carry the HDMU prefix (BHMA05154200 -> HDMUBHMA05154200 — client,
    2026-10-05), so the ERP, ICEGATE and the tracker all use one spelling. Anything else is kept as typed."""
    if bl is None:
        return None
    b = re.sub(r"\s+", "", bl).upper()
    return "HDMU" + b if b.startswith("BHMA") else bl


def identify(bl: Optional[str]) -> Optional[dict]:
    """{"line", "note", "icegate_mbl"} or None when the format isn't one we know. icegate_mbl = the number to
    search ICEGATE with (HMM without HDMU gets the prefix; stored MBLs already carry it — standard_mbl)."""
    b = re.sub(r"\s+", "", (bl or "")).upper()
    if not b:
        return None
    for pattern, line, note in RULES:
        if re.search(pattern, b):
            return {"line": line, "note": note.format(mbl=b) if note else None,
                    "icegate_mbl": f"HDMU{b}" if pattern == r"^BHMA" else b}
    return None


CONTAINER_RE = re.compile(r"^[A-Z]{4}\d{7}$")


def container_ok(no: str) -> bool:
    """Container number: 4 letters + 7 digits (e.g. MRKU5032093)."""
    return bool(CONTAINER_RE.match(re.sub(r"\s+", "", no or "").upper()))
