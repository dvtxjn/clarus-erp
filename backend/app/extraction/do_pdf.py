"""
Delivery Order (DO) -> each container's validity (client, 2026-10-05). The DO gives either the DO validity
("DO valid till") or the empty-return date per container; that is the container's actual last free date,
until the DO is revalidated (a newer DO replaces it). Read from the Maersk layout: the delivery itinerary
has one row per stop with a "validity" date and the containers it covers listed under it; a dated row that
lists no containers (e.g. the empty depot, or the terminal pickup on a merchant-haulage DO) covers the
containers no other row lists.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

CONTAINER = re.compile(r"\b([A-Z]{4}\d{7})\b")
STAMP = re.compile(r"(\d{4})-(\d{2})-(\d{2})\s+\d{1,2}:\d{2}")  # 2026-10-10 23:59
ROW = re.compile(r"^\s*(Full\s*Delivery|Cargo\s*Delivery|Empty\s*Container|Type\b)", re.I)
ITINERARY = re.compile(r"Delivery\s*Itinerary", re.I)


def _date(m: re.Match) -> Optional[date]:
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def scan_do_text(text: str) -> dict[str, Any]:
    """{"containers": {container_no: "YYYY-MM-DD"}, "valid_until": earliest date or None}. Empty when the
    layout isn't one we read (the containers' dates are then typed by hand)."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ITINERARY.search(ln)), None)
    listed: list[str] = []  # every container on the DO (equipment list + itinerary), in order
    for ln in lines:
        for no in CONTAINER.findall(ln):
            if no not in listed:
                listed.append(no)
    if start is None:
        return {"containers": {}, "valid_until": None, "listed": listed}

    blocks: list[tuple[date, list[str]]] = []
    current: Optional[tuple[date, list[str]]] = None
    for ln in lines[start + 1:]:
        if ROW.match(ln):
            current = None  # a new row of the itinerary
        m = STAMP.search(ln)
        if m and (d := _date(m)):
            current = (d, [])
            blocks.append(current)
        if current is not None:
            current[1].extend(n for n in CONTAINER.findall(ln) if n not in current[1])

    per: dict[str, date] = {}
    for d, nos in blocks:
        for no in nos:
            per[no] = d
    loose = [d for d, nos in blocks if not nos]
    if loose:
        for no in listed:
            per.setdefault(no, min(loose))
    return {"containers": {no: d.isoformat() for no, d in sorted(per.items())},
            "valid_until": min(per.values()).isoformat() if per else None, "listed": listed}
