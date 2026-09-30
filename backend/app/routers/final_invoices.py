"""Final invoices (tax / reimbursement): made from a proforma, edited by hand while
draft (every change audit-logged — this is what goes to the authorities), then issued
(numbered + locked). See app/invoice/final.py."""
from __future__ import annotations

import io

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import storage
from app.core.audit import record_change
from app.core.database import get_db
from app.core.deps import require_admin, require_billing_access
from app.core.locking import locked_proforma
from app.invoice.final import TAX_TYPES, NumberingNotSet, alter_until, check_series, number_for, compute, create_from_proforma, fy_of, issue
from app.models.settings import get_setting
from app.invoice.final_pdf import render_final_pdf
from app.models.final_invoice import FinalInvoice, InvoiceCounter
from app.models.proforma import Proforma
from app.models.soft_delete import soft_delete
from app.models.user import User

# Every route here is invoicing: admin-only, including reads (see require_billing_access)
router = APIRouter(tags=["final invoices"], dependencies=[Depends(require_billing_access)])


class FinalLine(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    sub_description: Optional[str] = Field(default=None, max_length=200)
    sac: Optional[str] = Field(default=None, max_length=20)
    tax_type: Literal["T", "P", "E", "R", "N"] = "T"
    non_gst_value: Decimal = Field(default=Decimal("0"), ge=0)
    taxable_value: Decimal = Field(default=Decimal("0"), ge=0)
    gst_rate: Decimal = Field(default=Decimal("0"), ge=0, le=28)


class FinalInvoiceUpdate(BaseModel):
    """Manual overrides. Draft: anything. Issued: irn / ack_no / ack_date any time; anything else
    until the 10th of next month (and, with e-invoicing, only while the e-invoice isn't filed)."""
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    customer: Optional[dict[str, Any]] = None
    header: Optional[dict[str, Any]] = None
    lines: Optional[list[FinalLine]] = None
    advance_received: Optional[Decimal] = Field(default=None, ge=0)
    remarks: Optional[str] = Field(default=None, max_length=500)
    irn: Optional[str] = Field(default=None, max_length=100)
    ack_no: Optional[str] = Field(default=None, max_length=50)
    ack_date: Optional[str] = Field(default=None, max_length=30)
    # altering an issued invoice with e-invoicing on: has its e-invoice (IRN) been filed?
    e_invoice_filed: Optional[bool] = None


class CancelIn(BaseModel):
    reason: Optional[str] = None


class CounterIn(BaseModel):
    fy: str = Field(pattern=r"^\d{2}-\d{2}$")
    next_seq: int = Field(ge=1)


def _get(db: Session, invoice_id: int) -> FinalInvoice:
    inv = db.get(FinalInvoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return inv


@router.post("/proformas/{proforma_id}/final-invoices", status_code=201)
def create_final_invoices(proforma_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_billing_access)):
    """Draft Tax Invoice (Billed by Clarus lines) + Reimbursement Invoice (charges paid
    by us). Existing DRAFTS from this proforma are replaced; issued ones are kept."""
    proforma = locked_proforma(db, proforma_id)  # shipment, then proforma: never two pairs at once
    issued = db.query(FinalInvoice).filter(FinalInvoice.proforma_id == proforma_id,
                                           FinalInvoice.status == "issued").count()
    if issued:
        raise HTTPException(status_code=400, detail="Final invoices from this proforma are already issued — "
                                                    "cancel them first, or make a new proforma version.")
    for old in db.query(FinalInvoice).filter(FinalInvoice.proforma_id == proforma_id, FinalInvoice.status == "draft").all():
        record_change(db, "final_invoices", old.id, "deleted", old.kind, "replaced by a new draft", user.id)
        soft_delete(db, old, user.id)
    created = create_from_proforma(db, proforma, user.id)
    if not created:
        raise HTTPException(status_code=400, detail="Nothing to invoice: no Billed by Clarus or paid-by-us charges on this proforma.")
    db.flush()
    for inv in created:
        record_change(db, "final_invoices", inv.id, "created", None, f"{inv.kind} from proforma {proforma_id}", user.id)
    db.commit()
    return [compute(i) for i in created]


def _register_row(inv: FinalInvoice, settled: Optional[dict] = None) -> dict:
    """One line of the invoice register (the Invoices page)."""
    d = compute(inv)
    paid = (settled or {}).get(inv.id, {"paid": Decimal("0"), "tds": Decimal("0")})
    done = paid["paid"] + paid["tds"]
    net = Decimal(d["totals"]["net_payable"])
    s = inv.shipment
    return {
        "id": inv.id, "kind": inv.kind, "status": inv.status, "number": inv.number, "seq": inv.seq, "fy": inv.fy,
        "invoice_date": d["invoice_date"], "customer": d["customer"].get("name") or "", "gstin": d["customer"].get("gstin") or "",
        "shipment_id": inv.shipment_id, "job": s.job if s else None, "mbl": s.mbl if s else None,
        "be_no": (inv.header or {}).get("be_no"), "not_applicable": d["not_applicable"],
        "taxable": d["totals"]["sub_taxable"], "non_gst": d["totals"]["sub_non_gst"], "gst": d["totals"]["gst"],
        "net_payable": d["totals"]["net_payable"], "irn": inv.irn,
        "received": str(done), "outstanding": str(max(Decimal("0"), net - done)) if inv.status == "issued" else "0",
    }


def _register(db: Session, fy: Optional[str], month: Optional[str], kind: Optional[str], status: Optional[str],
              client: Optional[str], q: Optional[str], ids: Optional[str] = None) -> list[FinalInvoice]:
    query = db.query(FinalInvoice)
    if ids:
        wanted = [int(x) for x in ids.split(",") if x.strip().isdigit()]
        query = query.filter(FinalInvoice.id.in_(wanted))
    if kind in ("tax", "reimbursement"):
        query = query.filter(FinalInvoice.kind == kind)
    if status in ("draft", "issued", "cancelled"):
        query = query.filter(FinalInvoice.status == status)
    rows = query.order_by(FinalInvoice.invoice_date.desc().nullslast(), FinalInvoice.seq.desc().nullslast(),
                          FinalInvoice.kind.desc()).all()
    out = []
    for inv in rows:
        d = inv.invoice_date
        if fy and (inv.fy or (fy_of(d) if d else None)) != fy:
            continue
        if month and (not d or f"{d:%Y-%m}" != month):
            continue
        if client and client.lower() not in ((inv.customer or {}).get("name") or "").lower():
            continue
        if q:
            s = inv.shipment
            hay = " ".join(str(x or "") for x in (inv.number, s.job if s else "", s.mbl if s else "",
                                                     (inv.header or {}).get("be_no"), inv.irn)).lower()
            if q.lower() not in hay:
                continue
        out.append(inv)
    return out


@router.get("/final-invoices")
def invoice_register(fy: Optional[str] = None, month: Optional[str] = None, kind: Optional[str] = None,
                     status: Optional[str] = None, client: Optional[str] = None, q: Optional[str] = None,
                     db: Session = Depends(get_db), _user: User = Depends(require_billing_access)):
    """Every final invoice (tax + reimbursement) across shipments, filtered — the Invoices page
    (client, 2026-09-30: print / extract without opening each shipment)."""
    rows = _register(db, fy, month, kind, status, client, q)
    from app.receivables import settled_by_invoice

    settled = settled_by_invoice(db, [r.id for r in rows])
    fys = sorted({r.fy or fy_of(r.invoice_date) for r in db.query(FinalInvoice).all() if r.fy or r.invoice_date}, reverse=True)
    return {"invoices": [_register_row(i, settled) for i in rows], "financial_years": fys}


@router.get("/final-invoices/export.pdf")
def export_pdf(ids: str, db: Session = Depends(get_db), _user: User = Depends(require_billing_access)):
    """The chosen invoices in one PDF (one per page, in the order listed) — to print or send."""
    import pypdfium2

    rows = _register(db, None, None, None, None, None, None, ids=ids)
    if not rows:
        raise HTTPException(status_code=404, detail="No invoices chosen")
    out = pypdfium2.PdfDocument.new()
    for inv in sorted(rows, key=lambda i: (i.fy or "", i.seq or 0, i.kind != "tax", i.id)):
        out.import_pages(pypdfium2.PdfDocument(render_final_pdf(compute(inv))))
    buf = io.BytesIO()
    out.save(buf)
    filename = f"Invoices ({len(rows)}).pdf"
    return Response(content=buf.getvalue(), media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Filename": quote(filename), "Access-Control-Expose-Headers": "X-Filename",
    })


@router.get("/final-invoices/register.xlsx")
def export_register(fy: Optional[str] = None, month: Optional[str] = None, kind: Optional[str] = None,
                    status: Optional[str] = None, client: Optional[str] = None, q: Optional[str] = None,
                    db: Session = Depends(get_db), _user: User = Depends(require_billing_access)):
    """The filtered register as an Excel sheet (number, date, client, GSTIN, job, BE, amounts, IRN)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    rows = [_register_row(i) for i in _register(db, fy, month, kind, status, client, q)]
    wb = Workbook()
    ws = wb.active
    ws.title = "Invoices"
    heads = ["Number", "Type", "Status", "Date", "Client", "GSTIN", "Job", "BL No", "BE No", "Taxable", "Non-GST", "GST",
             "Net payable", "IRN"]
    ws.append(heads)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append([r["number"] or "Draft", "Tax" if r["kind"] == "tax" else "Reimbursement", r["status"],
                   r["invoice_date"], r["customer"], r["gstin"], r["job"], r["mbl"], r["be_no"],
                   float(r["taxable"]), float(r["non_gst"]), float(r["gst"]), float(r["net_payable"]), r["irn"]])
    for col, w in zip("ABCDEFGHIJKLMN", (18, 14, 10, 12, 34, 18, 8, 20, 12, 13, 13, 12, 14, 30)):
        ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    filename = f"Invoice register{' ' + fy if fy else ''}.xlsx"
    return Response(content=buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
                             "X-Filename": quote(filename), "Access-Control-Expose-Headers": "X-Filename"})


@router.get("/shipments/{shipment_id}/final-invoices")
def list_final_invoices(shipment_id: int, db: Session = Depends(get_db), _user: User = Depends(require_billing_access)):
    rows = db.query(FinalInvoice).filter(FinalInvoice.shipment_id == shipment_id).order_by(FinalInvoice.id.desc()).all()
    return [compute(i) for i in rows]


def _pdf_name(data: dict, inv: FinalInvoice) -> str:
    number = (inv.number or f"DRAFT-{inv.id}").replace("/", "-")
    kind = "Tax Invoice" if inv.kind == "tax" else "Reimbursement Invoice"
    return f"{data['customer'].get('name') or 'Client'} - {number} - {kind}.pdf"


@router.get("/final-invoices/{invoice_id}.pdf")
def final_invoice_pdf(invoice_id: int, db: Session = Depends(get_db), _user: User = Depends(require_billing_access)):
    inv = _get(db, invoice_id)
    data = compute(inv)
    filename = _pdf_name(data, inv)
    return Response(content=render_final_pdf(data), media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Filename": quote(filename), "Access-Control-Expose-Headers": "X-Filename",
    })


@router.get("/final-invoices/{invoice_id}")
def get_final_invoice(invoice_id: int, db: Session = Depends(get_db), _user: User = Depends(require_billing_access)):
    return compute(_get(db, invoice_id))


@router.patch("/final-invoices/{invoice_id}")
def update_final_invoice(invoice_id: int, payload: FinalInvoiceUpdate, db: Session = Depends(get_db),
                         user: User = Depends(require_billing_access)):
    inv = _get(db, invoice_id)
    changes = payload.model_dump(exclude_unset=True, mode="json")
    filed = changes.pop("e_invoice_filed", None)
    altered = False
    if inv.status == "cancelled":
        raise HTTPException(status_code=400, detail="This invoice is cancelled.")
    if inv.status == "issued" and set(changes) - {"irn", "ack_no", "ack_date"}:
        # altering an issued bill (client, 2026-09-30): mistakes happen — allowed until the 10th of
        # next month; with e-invoicing, only while its e-invoice isn't filed
        until = alter_until(inv)
        if until is not None and date.today() > until:
            raise HTTPException(status_code=400, detail=f"Issued invoices can be altered until {until:%d %b %Y} "
                                "(that month's GSTR-1 is filed) — cancel it or issue a credit note instead.")
        if get_setting(db, "e_invoicing"):
            if inv.irn or filed:
                raise HTTPException(status_code=400, detail="Its e-invoice is filed, so it can't be altered — cancel "
                                    "the e-invoice (within 24 hours on the IRP) or issue a credit note.")
            if filed is None:
                raise HTTPException(status_code=409, detail={"ask": "e_invoice_filed",
                                                             "message": "Has the e-invoice for this bill been filed?"})
        altered = True
        if db.get_bind().dialect.name != "postgresql":
            raise HTTPException(status_code=400, detail="Altering issued invoices needs the Postgres database.")
        # the database lock lets this one transaction through (number / status stay fixed) — 0039
        db.execute(text("SET LOCAL clarus.invoice_alter = 'on'"))
    for field, value in changes.items():
        if field in ("invoice_date", "due_date") and value:
            value = date.fromisoformat(value)
        if field == "header":
            value = {**(inv.header or {}), **value}
        if field == "customer":
            value = {**(inv.customer or {}), **value}
        old = getattr(inv, field)
        if old != value:
            record_change(db, "final_invoices", inv.id, field, old, value, user.id)
            setattr(inv, field, value)
    if altered:
        record_change(db, "final_invoices", inv.id, "altered after issue", None, inv.number, user.id)
    db.commit()
    if altered:  # keep the corrected PDF as its own file (the issued one stays — nothing is deleted)
        data = compute(inv)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        storage.save_pdf(db, f"final_invoice_pdf_altered_{stamp}", inv.id, f"Invoices/{inv.fy}",
                         _pdf_name(data, inv).replace(".pdf", f" (altered {stamp}).pdf"), render_final_pdf(data))
        db.commit()
    db.refresh(inv)
    return compute(inv)


@router.post("/final-invoices/{invoice_id}/issue")
def issue_final_invoice(invoice_id: int, db: Session = Depends(get_db), user: User = Depends(require_billing_access)):
    """Number it (CL/<n>/<FY> or RI/CL/<n>/<FY>; the pair shares <n>) and lock it."""
    inv = _get(db, invoice_id)
    if inv.status != "draft":
        raise HTTPException(status_code=400, detail="Only a draft can be issued")
    if not inv.lines and not (inv.header or {}).get("not_applicable"):
        raise HTTPException(status_code=400, detail="The invoice has no lines")
    if not (inv.customer or {}).get("gstin"):
        raise HTTPException(status_code=400, detail="Enter the customer's GSTIN first (place of supply depends on it)")
    try:
        issue(db, inv)
    except NumberingNotSet as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    record_change(db, "final_invoices", inv.id, "issued", None, inv.number, user.id)
    db.commit()
    # what goes to the client / authorities: keep the PDF as issued (local + Drive)
    data = compute(inv)
    storage.save_pdf(db, "final_invoice_pdf", inv.id, f"Invoices/{inv.fy}", _pdf_name(data, inv),
                     render_final_pdf(data))
    db.commit()
    db.refresh(inv)
    return compute(inv)


@router.post("/proformas/{proforma_id}/final-invoices/issue")
def issue_pair(proforma_id: int, db: Session = Depends(get_db), user: User = Depends(require_billing_access)):
    """One action for the pair (client, 2026-09-30): number and lock the tax AND the
    reimbursement invoice together — same <n> — and keep both PDFs."""
    locked_proforma(db, proforma_id)
    drafts = (db.query(FinalInvoice).filter(FinalInvoice.proforma_id == proforma_id, FinalInvoice.status == "draft")
              .order_by(FinalInvoice.kind.desc()).all())  # tax first
    if not drafts:
        raise HTTPException(status_code=400, detail="No draft invoices to issue — make them from the proforma first")
    for inv in drafts:
        if not inv.lines and not (inv.header or {}).get("not_applicable"):
            raise HTTPException(status_code=400, detail=f"The {inv.kind} invoice has no lines")
        if not (inv.customer or {}).get("gstin"):
            raise HTTPException(status_code=400, detail="Enter the customer's GSTIN first (place of supply depends on it)")
    for inv in drafts:
        try:
            issue(db, inv)
        except NumberingNotSet as e:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(e))
        db.flush()  # so the second one finds the first's number (the pair shares <n>)
        record_change(db, "final_invoices", inv.id, "issued", None, inv.number, user.id)
    db.commit()
    for inv in drafts:
        data = compute(inv)
        storage.save_pdf(db, "final_invoice_pdf", inv.id, f"Invoices/{inv.fy}", _pdf_name(data, inv),
                         render_final_pdf(data))
    db.commit()
    return [compute(i) for i in drafts]


@router.get("/proformas/{proforma_id}/final-invoices.pdf")
def pair_pdf(proforma_id: int, db: Session = Depends(get_db), _user: User = Depends(require_billing_access)):
    """Both invoices of the pair in one PDF — tax invoice, then reimbursement (one per page).
    (Separate PDFs: /final-invoices/{id}.pdf for each.)"""
    import pypdfium2

    rows = (db.query(FinalInvoice).filter(FinalInvoice.proforma_id == proforma_id, FinalInvoice.status != "cancelled")
            .order_by(FinalInvoice.kind.desc(), FinalInvoice.id.desc()).all())
    pair = {}
    for inv in rows:  # newest of each kind
        pair.setdefault(inv.kind, inv)
    if not pair:
        raise HTTPException(status_code=404, detail="No final invoices for this proforma")
    out = pypdfium2.PdfDocument.new()
    for kind in ("tax", "reimbursement"):
        if kind in pair:
            out.import_pages(pypdfium2.PdfDocument(render_final_pdf(compute(pair[kind]))))
    buf = io.BytesIO()
    out.save(buf)
    first = pair.get("tax") or next(iter(pair.values()))
    data = compute(first)
    number = (first.number or f"DRAFT-{first.id}").replace("/", "-")
    filename = f"{data['customer'].get('name') or 'Client'} - {number} - Tax + Reimbursement.pdf"
    return Response(content=buf.getvalue(), media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Filename": quote(filename), "Access-Control-Expose-Headers": "X-Filename",
    })


@router.post("/final-invoices/{invoice_id}/cancel")
def cancel_final_invoice(invoice_id: int, payload: Optional[CancelIn] = None, db: Session = Depends(get_db),
                         user: User = Depends(require_admin)):
    """Admin: cancel an issued invoice. It's kept, and its number is never reused."""
    inv = _get(db, invoice_id)
    if inv.status != "issued":
        raise HTTPException(status_code=400, detail="Only an issued invoice can be cancelled")
    inv.status = "cancelled"
    inv.cancelled_at = datetime.now()
    inv.cancelled_by_id = user.id
    inv.cancel_reason = ((payload.reason if payload else None) or "").strip() or None
    record_change(db, "final_invoices", inv.id, "cancelled", inv.number, None, user.id)
    db.commit()
    return compute(inv)


@router.delete("/final-invoices/{invoice_id}", status_code=204)
def delete_final_draft(invoice_id: int, db: Session = Depends(get_db), user: User = Depends(require_billing_access)):
    """A draft: anyone who bills. An issued / cancelled one: the admin only (e.g. clearing trial invoices before
    going live, client 2026-09-30), never one with a payment set against it. Soft delete: restorable from
    Recently deleted, and its number is never given again."""
    from app.models.payment import PaymentAllocation

    inv = _get(db, invoice_id)
    if inv.status != "draft":
        if user.role.value != "admin":
            raise HTTPException(status_code=403, detail="Only the admin can delete an issued invoice — cancel it instead")
        if db.query(PaymentAllocation).filter(PaymentAllocation.final_invoice_id == inv.id).first():
            raise HTTPException(status_code=400, detail="A payment is set against this invoice — remove that first")
    record_change(db, "final_invoices", inv.id, "deleted", inv.number or inv.kind, None, user.id)
    soft_delete(db, inv, user.id)  # never removed from the database (a trigger refuses DELETE)
    db.commit()


@router.get("/invoice-counter")
def get_counters(db: Session = Depends(get_db), _user: User = Depends(require_billing_access)):
    rows = [{"fy": c.fy, "next_seq": c.next_seq} for c in db.query(InvoiceCounter).order_by(InvoiceCounter.fy)]
    now = fy_of(date.today())
    if not any(r["fy"] == now for r in rows):
        rows.append({"fy": now, "next_seq": None})  # not set yet: shown so the admin can set it
    return {"counters": rows, "tax_types": TAX_TYPES}


class SeriesIn(BaseModel):
    tax: str = Field(min_length=3, max_length=40)
    reimbursement: str = Field(min_length=3, max_length=40)


@router.get("/invoice-series")
def get_series(db: Session = Depends(get_db), _user: User = Depends(require_billing_access)):
    s = get_setting(db, "invoice_series")
    return {**s, "example_tax": number_for("tax", 201, fy_of(date.today()), s),
            "example_reimbursement": number_for("reimbursement", 201, fy_of(date.today()), s)}


@router.put("/invoice-series")
def set_series(payload: SeriesIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Admin: the number formats, e.g. CL/{n}/{fy}. Numbers already given don't change."""
    from app.models.settings import AppSetting

    new = {"tax": payload.tax.strip(), "reimbursement": payload.reimbursement.strip()}
    err = check_series(new)
    if err:
        raise HTTPException(status_code=422, detail=err)
    old = get_setting(db, "invoice_series")
    db.merge(AppSetting(key="invoice_series", value=new))
    record_change(db, "app_settings", 0, "invoice_series", str(old), str(new), user.id)
    db.commit()
    return get_series(db, user)


@router.put("/invoice-counter")
def set_counter(payload: CounterIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Admin: where the invoice series continues from (e.g. after the last invoice made elsewhere)."""
    c = db.get(InvoiceCounter, payload.fy)
    old = c.next_seq if c else None
    if c is None:
        c = InvoiceCounter(fy=payload.fy, next_seq=payload.next_seq)
        db.add(c)
    else:
        c.next_seq = payload.next_seq
    record_change(db, "invoice_counters", 0, payload.fy, old, payload.next_seq, user.id)
    db.commit()
    return {"fy": c.fy, "next_seq": c.next_seq}
