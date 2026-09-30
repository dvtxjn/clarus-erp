"""
Automatic update rules — what the ERP does by itself when a mail or an ICEGATE status arrives (client,
2026-09-30). The admin sees every rule as "IF … THEN …" in Settings, can switch each one off, and can add
their own simple rules:

  IF  a mail of type X arrives [and its text contains "…"]      THEN tick a field and/or flag Needs attention
  IF  ICEGATE's BE status queue is "…"                           THEN tick a field and/or flag Needs attention

Built-in rules are the ones the code has always followed; switching one off stops it, nothing else changes.
Custom rules only ever tick a box (set it to Yes) or raise Needs attention — never untick, never overwrite
a value. Old mails (older than `history_days`) and finished shipments are never changed by any rule.
Stored in app_settings["auto_rules"]: {"off": [ids], "custom": [...], "history_days": 45}.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.orm import Session

KEY = "auto_rules"
DEFAULT_HISTORY_DAYS = 45

# id -> (when, then); all on unless the admin switches them off
BUILTIN: dict[str, tuple[str, str]] = {
    "mail.be_ack": ("ICEGATE B/E Acknowledgement arrives", "Fill the BE no and BE date (only if empty)"),
    "mail.exam_order": ("ICEGATE Examination Order arrives", "Set Under examination (Yes / No as prescribed)"),
    "mail.documents": ("ICEGATE sends the assessed BE, OOC or gate pass PDF",
                       "Add it to Documents (reading it ticks OOC / Duty paid as for any upload)"),
    "mail.attention": ("ICEGATE Negative Ack, Query or Filing failed arrives", "Flag Needs attention"),
    "mail.settle": ("A later mail settles an open item (accepted after a Neg Ack, OOC after a Query)",
                    "Close the Needs attention item"),
    "status.duty_paid": ("ICEGATE BE status shows a payment date (or OOC)", "Tick Duty paid"),
    "status.examination": ("ICEGATE BE status shows an examination date, or the queue is ever INS",
                           "Tick Under examination (stays ticked)"),
    "status.ooc": ("ICEGATE BE status shows an OOC date", "Tick OOC and fill the OOC date (if empty)"),
    "status.queries": ("ICEGATE shows a query on our BE (BE no + date + port)", "Flag Needs attention; close it when replied"),
    "odex.do_released": ("ODeX: DO Released for a BL", "Tick DO (the DO number and date go on the timeline)"),
    "odex.do_rejected": ("ODeX: the line rejected the DO request", "Flag Needs attention with the line's remarks"),
    "odex.cfs_fill": ("ODeX: CFS request Confirmed", "Fill the CFS (only if empty)"),
}
DEFAULT_OFF = {"odex.cfs_fill"}  # ODeX writes the CFS's long code name; the tracker keeps short names

# boxes a custom rule may tick
TICK_FIELDS = {
    "duty_paid": "Duty paid", "ooc": "OOC", "do": "DO", "under_examination": "Under examination",
    "line_paid": "Line paid", "cfs_inv_received": "CFS invoice received",
}


def _raw(db: Session) -> dict:
    from app.models.settings import AppSetting

    row = db.get(AppSetting, KEY)
    return dict(row.value or {}) if row else {}


def on(db: Session, rule_id: str) -> bool:
    """Is this built-in rule switched on?"""
    st = _raw(db)
    off = st.get("off")
    return rule_id not in (off if off is not None else DEFAULT_OFF)


def history_days(db: Session) -> int:
    return int(_raw(db).get("history_days") or DEFAULT_HISTORY_DAYS)


def custom(db: Session, source: str) -> list[dict]:
    return [r for r in _raw(db).get("custom") or [] if r.get("source") == source and r.get("enabled", True)]


def matching_mail_rules(db: Session, kind: str, text: str) -> list[dict]:
    t = (text or "").lower()
    return [r for r in custom(db, "mail") if r.get("kind") == kind and (r.get("contains") or "").lower() in t]


def matching_queue_rules(db: Session, queue: Optional[str]) -> list[dict]:
    q = (queue or "").strip().upper()
    return [r for r in custom(db, "be_queue") if q and (r.get("queue") or "").strip().upper() == q]


def tick(db: Session, s, field: str, rule_label: str, user_id: Optional[int] = None) -> Optional[str]:
    """Set a box to Yes (never back to No). Returns a note when it changed."""
    from app.core.audit import record_change

    if field not in TICK_FIELDS or getattr(s, field):
        return None
    record_change(db, "shipments", s.id, field, getattr(s, field), True, user_id)
    setattr(s, field, True)
    return f"{TICK_FIELDS[field]} ticked (rule: {rule_label})"


# --- the Settings page ---
def describe(db: Session) -> dict:
    from app.icegate_mail.parse import LABELS

    st = _raw(db)
    off = st.get("off")
    off = set(off if off is not None else DEFAULT_OFF)
    return {
        "builtin": [{"id": k, "when": w, "then": t, "enabled": k not in off} for k, (w, t) in BUILTIN.items()],
        "custom": st.get("custom") or [],
        "history_days": int(st.get("history_days") or DEFAULT_HISTORY_DAYS),
        "fields": [{"field": k, "label": v} for k, v in TICK_FIELDS.items()],
        "kinds": [{"kind": k, "label": v} for k, v in LABELS.items() if k != "otp"],
    }


def validate(body: dict) -> dict:
    """The admin's edit -> what's stored. Raises ValueError with a readable message."""
    from app.icegate_mail.parse import LABELS

    off = [i for i in body.get("off") or [] if i in BUILTIN]
    days = int(body.get("history_days") or DEFAULT_HISTORY_DAYS)
    if not 1 <= days <= 3650:
        raise ValueError("Old-mail limit: between 1 and 3650 days")
    rules = []
    for r in body.get("custom") or []:
        src = r.get("source")
        if src not in ("mail", "be_queue"):
            raise ValueError("A rule starts from a mail type or the BE status queue")
        field = r.get("field") or None
        if field and field not in TICK_FIELDS:
            raise ValueError(f"Can't tick {field}")
        if not field and not r.get("attention"):
            raise ValueError("A rule must tick a box or flag Needs attention")
        clean = {"id": r.get("id") or uuid.uuid4().hex[:8], "source": src, "field": field,
                 "attention": bool(r.get("attention")), "enabled": bool(r.get("enabled", True))}
        if src == "mail":
            if r.get("kind") not in LABELS or r.get("kind") == "otp":
                raise ValueError("Pick the mail type the rule is for")
            clean["kind"] = r["kind"]
            clean["contains"] = (r.get("contains") or "").strip()[:120]
        else:
            q = (r.get("queue") or "").strip().upper()
            if not q or len(q) > 12:
                raise ValueError("Type the queue code, e.g. INS or SUP")
            clean["queue"] = q
        rules.append(clean)
    return {"off": off, "custom": rules, "history_days": days}
