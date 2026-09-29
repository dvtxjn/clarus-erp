"""
Shipment status from evidence (backlog item B).

A status is set by the evidence that proves it, not typed by hand. Edit the
RULES table to change what counts as evidence — nothing else needs to change.
Later a Playwright job can verify some of these against ICEGATE (e.g. IGM).

Behaviour (apply_status_rules):
  - evidence added   -> status moves FORWARD to the furthest step proven
  - evidence removed -> if the current status is no longer proven, it moves
                        back to the furthest step that still is
  - Billed is left alone (it's controlled by Bill / cancel bill)
  - statuses with no evidence rule (Under OOC) can still be set by hand
"""
from __future__ import annotations

from typing import Callable, Optional

from app.core.enums import ShipmentStatus
from app.models.shipment import Shipment


def _filled(v) -> bool:
    return v is not None and str(v).strip() != ""


# (status, what proves it, fields that count as evidence) — pipeline order
RULES: list[tuple[ShipmentStatus, Callable[[Shipment], bool], tuple[str, ...]]] = [
    (ShipmentStatus.IGM_FILED, lambda s: _filled(s.igm), ("igm",)),
    (ShipmentStatus.BE_FILED, lambda s: _filled(s.be_no), ("be_no",)),
    (ShipmentStatus.BE_ASSESSED, lambda s: s.duty_amount is not None, ("duty_amount",)),
    (ShipmentStatus.DUTY_PAID, lambda s: bool(s.duty_paid), ("duty_paid",)),
    (ShipmentStatus.OOC_DONE, lambda s: bool(s.ooc), ("ooc",)),
    # Cleared needs the Cleared Date AND Duty, CFS Inv, Line, OOC, DO all ticked
    (ShipmentStatus.CLEARED, lambda s: s.is_fully_cleared,
     ("cleared_date", "duty_paid", "cfs_inv_received", "line_paid", "ooc", "do")),
]

EVIDENCE_FIELDS = {f for _, _, fields in RULES for f in fields}
_ORDER = list(ShipmentStatus)


def proven_status(s: Shipment) -> ShipmentStatus:
    """Furthest pipeline step the shipment's evidence proves."""
    best = ShipmentStatus.TO_BE_FILED
    for status, proves, _ in RULES:
        if proves(s) and _ORDER.index(status) > _ORDER.index(best):
            best = status
    return best


def status_after_evidence_change(s: Shipment) -> Optional[ShipmentStatus]:
    """New status after evidence changed, or None to leave it as it is."""
    if s.status == ShipmentStatus.BILLED:
        return None
    proven = proven_status(s)
    current = _ORDER.index(s.status)
    if _ORDER.index(proven) > current:
        return proven  # evidence added
    still_proven = any(st == s.status and proves(s) for st, proves, _ in RULES)
    has_rule = any(st == s.status for st, _, _ in RULES)
    if has_rule and not still_proven and _ORDER.index(proven) < current:
        return proven  # the evidence behind the current status was removed
    return None
