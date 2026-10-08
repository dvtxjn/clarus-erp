"""
ICEGATE mails -> shipments (client, 2026-09-30, P1).

Import: each mail read once (fingerprint), stored, matched, applied. Unmatched mails wait — every import
tries them again (a BE Ack tells us the BE number, after which the other mails of that BE match too).

Matching: BE No (+ port) first; the job number (+ port) for the Ack / Neg Ack / Submit mails, which carry no
BE No yet (LiveImpex job no = tracker job, checked on real mails); the MBL / HBL for eSANCHIT uploads.

What a mail changes (identifiers only fill blanks — a different value is noted, never overwritten):
  B/E Acknowledgement   BE No + BE date; status -> BE Filed (evidence rule)
  Examination Order     under examination yes / no (the OOC copy later says for sure)
  Processed B/E, Out of Charge, Gate Pass: the PDF is added as a document (Assessed BE / OOC BE / Gatepass
      BE) through the normal upload path — same reading and tracker updates as a hand upload
  B/E Negative Ack, B/E Query, Filing failed: "Needs attention" until someone marks it done — or on its own
      when a later mail settles it (Ack for the same job; OOC / Gate Pass for the queried BE)
"""
from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.core.audit import record_change
from app.core.enums import DocumentType
from app.core.status_rules import status_after_evidence_change
from app.icegate_mail.parse import parse
from app.models.document import ShipmentDocument
from app.models.icegate_mail import IcegateMail
from app.models.shipment import Shipment
from app.models.user import User

MAX_FILE = 25 * 1024 * 1024
# Older mail (e.g. the 2,000+ mails moved from the old inbox, client 2026-09-30) is history only: it goes on
# the shipment's timeline but changes nothing, adds no documents and raises no "Needs attention".
HISTORY_DAYS = 45
IST = timezone(timedelta(hours=5, minutes=30))  # office time (client: GMT+5:30)


def _norm(v: Optional[str]) -> str:
    return "".join((v or "").split()).upper()


def unpack(name: str, data: bytes) -> Iterable[bytes]:
    """.eml files as they come, or every .eml inside a .zip (Gmail "Download all")."""
    if name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                if info.filename.lower().endswith(".eml") and info.file_size <= MAX_FILE:
                    yield z.read(info)
    elif name.lower().endswith(".eml"):
        yield data


def match(db: Session, m: IcegateMail) -> Optional[Shipment]:
    def one(q):
        rows = q.all()
        if m.port:
            same = [s for s in rows if _norm(s.port) == _norm(m.port)]
            rows = same or [s for s in rows if not s.port]
        live = [s for s in rows if not s.is_archived]
        rows = live if len(rows) > 1 and live else rows
        return rows[0] if len(rows) == 1 else None

    if m.be_no:
        q = db.query(Shipment).filter(Shipment.be_no == m.be_no)
        if m.be_date:  # BE numbers are reused every year (client): the date must agree when both are known
            q = q.filter((Shipment.be_dt == m.be_date) | (Shipment.be_dt.is_(None)))
        s = one(q)
        if s:
            return s
    if m.job_no:
        s = one(db.query(Shipment).filter(Shipment.job == m.job_no))
        if s:
            return s
    if m.mbl:
        ref = _norm(m.mbl)
        cands = db.query(Shipment).filter((Shipment.mbl.ilike(f"%{ref}%")) | (Shipment.hbl.ilike(f"%{ref}%")))
        return one(cands)
    return None


def _apply(db: Session, m: IcegateMail, s: Shipment, user: Optional[User]) -> list[str]:
    """What a mail changes on its shipment — each step is an automatic rule the admin can switch off
    (Settings → Automatic rules, app/auto_rules.py), plus the admin's own rules for this mail type."""
    from app import auto_rules

    notes: list[str] = []
    uid = user.id if user else None
    notes += _custom_rules(db, m, s, uid)

    def fill(field: str, value) -> None:
        if value in (None, ""):
            return
        old = getattr(s, field)
        if old in (None, ""):
            record_change(db, "shipments", s.id, field, old, value, uid)
            setattr(s, field, value)
            notes.append(f"{field.replace('_', ' ').upper()} set to {value}")
        elif _norm(str(old)) != _norm(str(value)):
            notes.append(f"ICEGATE says {field.replace('_', ' ').upper()} {value}; tracker has {old} — not changed")

    if m.kind == "odex_do_released":
        if auto_rules.on(db, "odex.do_released"):
            d = m.detail or {}
            note = auto_rules.tick(db, s, "do", "ODeX DO released", uid)
            notes.append(note or "DO already ticked")
            if d.get("do_no"):
                notes.append(f"DO {d['do_no']} dated {d.get('do_date') or '—'}")
    elif m.kind == "odex_cfs":
        d = m.detail or {}
        if auto_rules.on(db, "odex.cfs_fill") and d.get("status") == "Confirmed" and d.get("cfs_name"):
            fill("cfs", d["cfs_name"])
    elif m.kind.startswith("odex_"):
        pass  # on the timeline
    elif m.kind == "be_ack" and auto_rules.on(db, "mail.be_ack"):
        fill("be_no", m.be_no)
        fill("be_dt", m.be_date)
        new = status_after_evidence_change(s)
        if new:
            record_change(db, "shipments", s.id, "status", s.status, new, uid)
            s.status = new
    elif m.kind == "exam_order" and auto_rules.on(db, "mail.exam_order"):
        prescribed = bool((m.detail or {}).get("prescribed"))
        if s.under_examination is None or (prescribed and not s.under_examination):
            record_change(db, "shipments", s.id, "under_examination", s.under_examination, prescribed, uid)
            s.under_examination = prescribed
            notes.append("Examination ordered" if prescribed else "No examination")
    elif m.pdf and user is not None and auto_rules.on(db, "mail.documents"):
        from app.routers.documents import _store_document

        doc_type = DocumentType[(m.detail or {}).get("doc_type") or ""]
        dup = (db.query(ShipmentDocument).filter(ShipmentDocument.shipment_id == s.id,
                                                 ShipmentDocument.original_filename == m.pdf_name).first()
               or db.query(ShipmentDocument).filter(ShipmentDocument.shipment_id == s.id,
                                                    ShipmentDocument.document_type == doc_type).first())
        if dup:  # this copy (or one of the same kind, uploaded by hand) is already there: no duplicate
            m.document_id = dup.id
            notes.append("Already on the shipment — not added again")
        else:
            data = m.pdf
            db.flush()
            doc = _store_document(db, s, doc_type, m.pdf_name, lambda f: f.write(data), user)
            m.document_id = doc.id
            notes.extend((doc.extraction or {}).get("notes") or [])
            notes.append({"ASSESSED_BILL_OF_ENTRY": "Assessed BE copy added", "OOC_BILL_OF_ENTRY": "OOC copy added",
                          "GATEPASS_BILL_OF_ENTRY": "OOC gate pass added"}[doc_type.name])
        m.pdf = None
    return notes


def _custom_rules(db: Session, m: IcegateMail, s: Shipment, uid: Optional[int]) -> list[str]:
    """The admin's own rules: IF a mail of this type [containing …] THEN tick a box / Needs attention."""
    from app import auto_rules

    notes = []
    text = " ".join(x for x in (m.subject, m.summary) if x)
    for r in auto_rules.matching_mail_rules(db, m.kind, text):
        label = f"{m.label}{' containing “' + r['contains'] + '”' if r.get('contains') else ''}"
        if r.get("field"):
            note = auto_rules.tick(db, s, r["field"], label, uid)
            if note:
                notes.append(note)
        if r.get("attention") and not m.resolved_at:
            m.attention = True
            notes.append(f"Needs attention (rule: {label})")
    return notes


def _ts(d: Optional[datetime]) -> datetime:
    """Comparable time (SQLite hands back naive datetimes; those are UTC)."""
    if d is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _settle(db: Session, m: IcegateMail) -> None:
    """A later mail that settles an open attention item closes it."""
    from app import auto_rules

    if not auto_rules.on(db, "mail.settle"):
        return
    now = datetime.now(timezone.utc)
    q = db.query(IcegateMail).filter(IcegateMail.attention.is_(True), IcegateMail.resolved_at.is_(None),
                                     IcegateMail.id != m.id)
    if m.kind in ("be_ack", "be_ack_amend", "be_generated", "processed_be") and (m.job_no or m.shipment_id):
        # the same job (by job no, or the shipment it was matched to) filed again and accepted
        same = (IcegateMail.job_no == m.job_no) if m.job_no else (IcegateMail.shipment_id == m.shipment_id)
        if m.job_no and m.shipment_id:
            same = same | (IcegateMail.shipment_id == m.shipment_id)
        for x in q.filter(IcegateMail.kind.in_(("be_nak", "be_rejected", "filing_failed")), same):
            if _ts(x.received_at) <= _ts(m.received_at):
                x.resolved_at, x.resolved_note = now, "Filed again and accepted"
    if m.kind in ("out_of_charge", "gate_pass") and m.be_no:
        for x in q.filter(IcegateMail.kind == "be_query", IcegateMail.be_no == m.be_no):
            x.resolved_at, x.resolved_note = now, "Out of charge given"
    if m.kind == "odex_do_released" and m.mbl:  # the DO came after all: an earlier rejection is settled
        for x in q.filter(IcegateMail.kind == "odex_do_rejected", IcegateMail.mbl == m.mbl):
            if _ts(x.received_at) <= _ts(m.received_at):
                x.resolved_at, x.resolved_note = now, "DO released"


def is_history(m: IcegateMail, days: Optional[int] = None) -> bool:
    """Older than the admin's old-mail limit (Settings → Automatic rules; default 45 days)."""
    return m.received_at is not None and datetime.now(timezone.utc) - _ts(m.received_at) > timedelta(days=days or HISTORY_DAYS)


def link(db: Session, m: IcegateMail, user: Optional[User]) -> None:
    """Match (if not yet) and apply (once)."""
    if m.shipment_id is None:
        s = match(db, m)
        if s is None:
            return
        m.shipment_id = s.id
    if m.applied:
        return
    s = db.get(Shipment, m.shipment_id)
    from app import auto_rules

    if is_history(m, auto_rules.history_days(db)) or s.is_archived or s.is_billed:
        m.notes = ["Older mail / finished shipment — on the timeline only, nothing changed"]
        m.pdf = None
        m.applied = True
        return
    if m.pdf and user is None:
        return  # documents are added on an import by a person
    m.notes = _apply(db, m, s, user)
    m.applied = True


def _attention_on(db: Session, kind: str) -> bool:
    from app import auto_rules

    rule = {"odex_do_rejected": "odex.do_rejected"}.get(kind, "mail.attention")
    return auto_rules.on(db, rule)


def import_mails(db: Session, raws: Iterable[bytes], user: Optional[User]) -> dict:
    from app import auto_rules

    days = auto_rules.history_days(db)
    out = {"read": 0, "new": 0, "duplicates": 0, "ignored": 0, "matched": 0, "attention": 0}
    for raw in raws:
        out["read"] += 1
        fp = hashlib.sha256(raw).hexdigest()
        if db.query(IcegateMail.id).filter(IcegateMail.fingerprint == fp).first():
            out["duplicates"] += 1
            continue
        ev = parse(raw)
        if ev is None:
            out["ignored"] += 1
            continue
        if ev["received_at"] and ev["received_at"].tzinfo:  # stored as UTC (SQLite keeps no offset)
            ev["received_at"] = ev["received_at"].astimezone(timezone.utc)
        detail = dict(ev["detail"])
        if ev["pdf"]:
            detail["doc_type"] = ev["pdf"]["doc_type"]
        m = IcegateMail(fingerprint=fp, message_id=ev["message_id"], received_at=ev["received_at"], kind=ev["kind"],
                        label=ev["label"], subject=ev["subject"], summary=ev["summary"], be_no=ev["be_no"],
                        be_date=ev["be_date"], job_no=ev["job_no"], port=ev["port"], mbl=ev["mbl"], detail=detail,
                        attention=ev["attention"], imported_by_id=user.id if user else None,
                        pdf_name=ev["pdf"]["name"] if ev["pdf"] else None, pdf=ev["pdf"]["data"] if ev["pdf"] else None)
        if is_history(m, days):  # old: no "Needs attention", and no PDF kept waiting in the database
            m.attention, m.pdf = False, None
        elif m.attention and not _attention_on(db, m.kind):
            m.attention = False  # the admin switched that rule off
        db.add(m)
        db.flush()
        out["new"] += 1
    # oldest first: an Ack fills the BE No before that BE's other mails are matched
    pending = (db.query(IcegateMail).filter((IcegateMail.shipment_id.is_(None)) | (IcegateMail.applied.is_(False)))
               .order_by(IcegateMail.received_at.asc().nullsfirst(), IcegateMail.id).all())
    for m in pending:
        was = m.shipment_id
        link(db, m, user)
        db.flush()
        if m.shipment_id and not was:
            out["matched"] += 1
    for m in sorted(pending, key=lambda x: _ts(x.received_at)):
        _settle(db, m)
    db.commit()
    out["attention"] = db.query(IcegateMail).filter(IcegateMail.attention.is_(True),
                                                    IcegateMail.resolved_at.is_(None)).count()
    return out
