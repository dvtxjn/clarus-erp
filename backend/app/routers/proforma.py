from datetime import date
from decimal import Decimal
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app import storage
from app.core.audit import record_change
from app.core.database import get_db
from app.core.deps import get_current_user, require_admin, require_billing_access
from app.core.locking import locked_proforma, locked_shipment
from app.core.enums import ChargeCalculationBasis, ChargeCategory, ProformaStatus
from app.invoice.final import fy_of
from app.invoice.autofill import DERIVED_CODES, line_key, restore_line, sync_proforma
from fastapi.encoders import jsonable_encoder

from app.invoice.build import GST_DIFFERENCE_CODE, clarus_total, match_total, round_off, be_importer_name, copy_for, documents_not_attached, build_invoice, invoice_filename, value_summary, weight_kgs
from app.invoice.lines import container_count, new_line, recalc, sync_gst_difference
from app.invoice.pdf import render_pdf
from app.invoice.xlsx import render_xlsx
from app.models.charge import ChargeMasterEntry
from app.models.organization import OrganizationEntry
from app.models.licence import Licence
from app.models.pricing_rule import PricingRule
from app.models.proforma import Proforma, ProformaLineItem, ProformaSnapshot
from app.models.storage import StoredFile
from app.models.soft_delete import soft_delete
from app.models.shipment import Shipment
from app.models.user import User
from app.schemas.proforma import (
    ChargeMasterOut,
    ChargeMasterCreate,
    ChargeMasterUpdate,
    PricingRuleIn,
    LicenceIn,
    LicenceOut,
    PricingRuleOut,
    ProformaOut,
    ProformaLineItemCreate,
    ProformaLineItemOut,
    ProformaSnapshotOut,
    ProformaStatusUpdate,
    ProformaCreate,
    ProformaLineItemUpdate,
    FillResult,
    RestoreIn,
)

# Every route here is invoicing: admin-only, including reads (see require_billing_access)
router = APIRouter(tags=["proforma"], dependencies=[Depends(require_billing_access)])


@router.get("/charge-master", response_model=list[ChargeMasterOut])
def list_charge_master(include_inactive: bool = False, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    """Spec §5.4: the user-manageable library of chargeable line items a
    proforma's line items are picked from (standard rates prefill new lines)."""
    q = db.query(ChargeMasterEntry)
    if not include_inactive:
        q = q.filter(ChargeMasterEntry.is_active.is_(True))
    return q.order_by(ChargeMasterEntry.name).all()


# worked out by the app, not a rate someone types
FIXED_CHARGES = {GST_DIFFERENCE_CODE}


@router.patch("/charge-master/{charge_id}", response_model=ChargeMasterOut)
def update_charge(charge_id: int, payload: ChargeMasterUpdate, db: Session = Depends(get_db),
                  current_user: User = Depends(require_admin)):
    """Rates screen (admin): standard rate and details. Existing proforma lines keep
    the rate / SAC / GST they were created with."""
    charge = db.get(ChargeMasterEntry, charge_id)
    if not charge:
        raise HTTPException(status_code=404, detail="Charge not found")
    changes = payload.model_dump(exclude_unset=True)
    if charge.code in FIXED_CHARGES and set(changes) - {"name"}:
        raise HTTPException(status_code=400, detail=f"{charge.name} is worked out automatically")
    for field, value in changes.items():
        if field != "default_rate" and value is None:
            continue
        if getattr(charge, field) != value:
            record_change(db, "charge_master_entries", charge.id, field, getattr(charge, field), value, current_user.id)
            setattr(charge, field, value)
    db.commit()
    db.refresh(charge)
    return charge


@router.post("/charge-master", response_model=ChargeMasterOut, status_code=201)
def create_charge(payload: ChargeMasterCreate, db: Session = Depends(get_db),
                  current_user: User = Depends(require_admin)):
    """A new chargeable item — immediately selectable on any proforma."""
    if db.query(ChargeMasterEntry).filter(ChargeMasterEntry.code == payload.code).first():
        raise HTTPException(status_code=400, detail="A charge with this code already exists")
    charge = ChargeMasterEntry(**payload.model_dump(), is_active=True)
    db.add(charge)
    db.flush()
    record_change(db, "charge_master_entries", charge.id, "created", None, f"{charge.code} {charge.name}", current_user.id)
    db.commit()
    db.refresh(charge)
    return charge


# --- Licence rates (Rates screen): charges pre-filled on proformas per licence ---

@router.get("/licences", response_model=list[LicenceOut])
def list_licences(db: Session = Depends(get_db), current_user: User = Depends(require_billing_access)):
    return db.query(Licence).order_by(Licence.is_active.desc(), Licence.number).all()


def _licence_payload(db: Session, payload: LicenceIn) -> dict:
    codes = {c for (c,) in db.query(ChargeMasterEntry.code)}
    unknown = [r.code for r in payload.rates if r.code not in codes]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown charge code(s): {', '.join(unknown)}")
    data = payload.model_dump(mode="json")
    data["number"] = data["number"].strip()
    data["rates"] = [{k: v for k, v in r.items() if v not in (None, "", "0", 0)} | {"code": r["code"]}
                     for r in data["rates"]]
    return data


@router.post("/licences", response_model=LicenceOut, status_code=201)
def create_licence(payload: LicenceIn, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    data = _licence_payload(db, payload)
    if db.query(Licence).filter(Licence.number == data["number"]).first():
        raise HTTPException(status_code=400, detail="This licence already exists")
    lic = Licence(**data)
    db.add(lic)
    db.flush()
    record_change(db, "licences", lic.id, "created", None, lic.number, current_user.id)
    db.commit()
    db.refresh(lic)
    return lic


@router.put("/licences/{licence_id}", response_model=LicenceOut)
def update_licence(licence_id: int, payload: LicenceIn, db: Session = Depends(get_db),
                   current_user: User = Depends(require_admin)):
    lic = db.get(Licence, licence_id)
    if not lic:
        raise HTTPException(status_code=404, detail="Licence not found")
    for field, value in _licence_payload(db, payload).items():
        if getattr(lic, field) != value:
            record_change(db, "licences", lic.id, field, getattr(lic, field), value, current_user.id)
            setattr(lic, field, value)
    db.commit()
    db.refresh(lic)
    return lic


# --- HSS pricing rules (Rates screen) ---

@router.get("/pricing-rules", response_model=list[PricingRuleOut])
def list_pricing_rules(db: Session = Depends(get_db), current_user: User = Depends(require_billing_access)):
    return db.query(PricingRule).order_by(PricingRule.importer_name, PricingRule.seller_name, PricingRule.bill_to_role).all()


def _rule_payload(db: Session, payload: PricingRuleIn) -> dict:
    codes = {c for (c,) in db.query(ChargeMasterEntry.code)}
    unknown = [ln.code for ln in payload.lines if ln.code not in codes]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown charge code(s): {', '.join(unknown)}")
    data = payload.model_dump(mode="json")
    data["lines"] = [{k: v for k, v in ln.items() if v not in (None, "0", 0)} | {"code": ln["code"]} for ln in data["lines"]]
    return data


@router.post("/pricing-rules", response_model=PricingRuleOut, status_code=201)
def create_pricing_rule(payload: PricingRuleIn, db: Session = Depends(get_db),
                        current_user: User = Depends(require_admin)):
    rule = PricingRule(**_rule_payload(db, payload))
    db.add(rule)
    db.flush()
    record_change(db, "pricing_rules", rule.id, "created", None, rule.name, current_user.id)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/pricing-rules/{rule_id}", response_model=PricingRuleOut)
def update_pricing_rule(rule_id: int, payload: PricingRuleIn, db: Session = Depends(get_db),
                        current_user: User = Depends(require_admin)):
    rule = db.get(PricingRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    data = _rule_payload(db, payload)
    for field, value in data.items():
        if getattr(rule, field) != value:
            record_change(db, "pricing_rules", rule.id, field, getattr(rule, field), value, current_user.id)
            setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/pricing-rules/{rule_id}", status_code=204)
def delete_pricing_rule(rule_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    rule = db.get(PricingRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    record_change(db, "pricing_rules", rule.id, "deleted", rule.name, None, current_user.id)
    db.delete(rule)
    db.commit()


@router.get("/shipments/{shipment_id}/proformas", response_model=list[ProformaOut])
def list_proformas(
    shipment_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_billing_access)
):
    """Spec §5.2: full version history, newest first."""
    proformas = (
        db.query(Proforma).filter(Proforma.shipment_id == shipment_id).order_by(Proforma.version_number.desc()).all()
    )
    return [_to_out(p) for p in proformas]


@router.post("/shipments/{shipment_id}/proformas", response_model=ProformaOut, status_code=201)
def create_proforma(
    shipment_id: int,
    payload: Optional[ProformaCreate] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_billing_access),
):
    """One live invoice per shipment (client, 2026-10-08: no v1 / v2 — the invoice is edited in place, and a
    sent copy is kept under its history). HSS shipments: one each for the seller and the buyer, both billed
    to the BE importer (the buyer)."""
    payload = payload or ProformaCreate()
    shipment = locked_shipment(db, shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    _require_documents(shipment)

    last = (  # deleted drafts count too: a version number is never reused
        db.query(Proforma).filter(Proforma.shipment_id == shipment_id).order_by(Proforma.version_number.desc())
        .execution_options(include_deleted=True).first()
    )
    next_version = (last.version_number + 1) if last else 1

    role = payload.bill_to_role
    if role and not shipment.is_hss:
        raise HTTPException(status_code=400, detail="Seller/buyer invoices are only for HSS shipments.")
    if shipment.is_hss and not role:
        raise HTTPException(status_code=400, detail="This is an HSS shipment — choose whether the invoice is for the seller or the buyer.")
    # Client rule: Bill To is always the BE importer (name on the BE; until a BE is
    # read, the tracker's buyer / consignee). The seller/buyer role only says whose copy it is.
    bill_to = be_importer_name(shipment) or (shipment.hss_buyer if shipment.is_hss else shipment.consignee)

    # one live invoice (per HSS party): it is edited, never replaced by a new version
    if db.query(Proforma).filter(Proforma.shipment_id == shipment_id, Proforma.bill_to_role == role,
                                 Proforma.status != ProformaStatus.SUPERSEDED).first():
        raise HTTPException(status_code=409, detail="This shipment already has its invoice — edit it instead.")
    proforma = Proforma(
        shipment_id=shipment_id,
        version_number=next_version,
        name=(payload.name or "").strip() or None,
        bill_to=bill_to,
        bill_to_role=role,
        created_by_id=current_user.id,
        extracted_data={
            "mbl": shipment.mbl,
            "hbl": shipment.hbl,
            "be_no": shipment.be_no,
            "consignee": shipment.consignee,
        },
    )
    db.add(proforma)
    db.flush()
    partner = _hss_partner(db, proforma)
    if partner is not None and partner.bill_rate_manual:
        proforma.bill_rate, proforma.bill_rate_manual = partner.bill_rate, True
    # charges pre-filled: licence rates, HSS rule, and everything the documents know
    sync_proforma(db, proforma, full=True)
    db.commit()
    db.refresh(proforma)
    return _to_out(proforma)


@router.post("/proformas/{proforma_id}/line-items", response_model=ProformaOut, status_code=201)
def add_line_item(
    proforma_id: int,
    payload: ProformaLineItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_billing_access),
):
    """Spec §5.3: any combination of charges from the charge master, not a
    fixed set of columns — GST/SAC are copied from the charge master at
    time of use so a later edit to the master doesn't rewrite past bills."""
    proforma = locked_proforma(db, proforma_id)
    if not proforma:
        raise HTTPException(status_code=404, detail="Proforma not found")
    charge = db.query(ChargeMasterEntry).filter(ChargeMasterEntry.id == payload.charge_master_id).first()
    if not charge:
        raise HTTPException(status_code=404, detail="Charge master entry not found")

    _require_draft(proforma, db, current_user)
    if charge.code == GST_DIFFERENCE_CODE:
        raise HTTPException(status_code=400, detail="GST Difference is worked out automatically — enter the Bill Rate instead.")
    if charge.code == "ROY" and not proforma.shipment.is_hss:
        raise HTTPException(status_code=400, detail="Royalty only applies to HSS shipments.")
    quantity = payload.quantity
    if quantity is None:
        if charge.calculation_basis == ChargeCalculationBasis.PER_KG:
            quantity = weight_kgs(proforma.shipment)
            if quantity is None:
                raise HTTPException(status_code=400, detail=(
                    f"{charge.name} is charged per kg, but this shipment has no gross weight — "
                    "upload the BE or enter the quantity."))
        elif charge.calculation_basis == ChargeCalculationBasis.PER_CONTAINER:
            quantity = container_count(proforma.shipment)
            if quantity is None:
                raise HTTPException(status_code=400, detail=(
                    f"{charge.name} is charged per container, but this shipment has no container count — "
                    "fill in Cntr on the shipment or enter the quantity."))
        else:
            quantity = Decimal("1")
    line_item = new_line(proforma, charge, payload.rate, quantity, payload.description,
                          payload.category, payload.gst_amount)
    db.add(line_item)
    proforma.line_items.append(line_item)
    sync_gst_difference(db, proforma)
    db.commit()
    db.refresh(proforma)
    return _to_out(proforma)


def _require_documents(shipment: Shipment) -> None:
    """No proforma is generated until the documents it is worked out from are attached."""
    missing = documents_not_attached(shipment)
    if missing:
        raise HTTPException(status_code=409, detail=f"Not attached: {', '.join(missing)}. "
                                                    "Attach it to the shipment first — the proforma is worked out from it.")


def _require_draft(proforma: Proforma, db: Optional[Session] = None, user: Optional[User] = None) -> None:
    """Edits go to the same (working) invoice. A sent one is reopened: the copy that went to
    the client is kept in history first (client, 2026-10-07). Old superseded versions stay as they are."""
    if proforma.status == ProformaStatus.SENT and db is not None:
        _reopen_sent(db, proforma, user)
    elif proforma.status != ProformaStatus.DRAFT:
        raise HTTPException(status_code=400, detail="This is an old version — edit the current invoice instead.")


def _reopen_sent(db: Session, proforma: Proforma, user: Optional[User]) -> None:
    sf = db.query(StoredFile).filter(StoredFile.kind == "proforma_pdf", StoredFile.ref_id == proforma.id).first()
    out = _to_out(proforma)
    db.add(ProformaSnapshot(
        proforma_id=proforma.id, bill_rate=proforma.bill_rate, grand_total=out.grand_total,
        invoice=jsonable_encoder(build_invoice(proforma)), proforma_data=jsonable_encoder(out),
        drive_file_id=sf.drive_file_id if sf else None, created_by_id=user.id if user else None))
    if sf is not None:
        sf.kind = "proforma_pdf_old"  # the next send saves a fresh PDF
    record_change(db, "proformas", proforma.id, "status", ProformaStatus.SENT, ProformaStatus.DRAFT,
                  user.id if user else None)
    proforma.status = ProformaStatus.DRAFT
    db.flush()
    db.refresh(proforma)


@router.patch("/proformas/{proforma_id}/line-items/{line_item_id}", response_model=ProformaOut)
def update_line_item(
    proforma_id: int,
    line_item_id: int,
    payload: ProformaLineItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_billing_access),
):
    """Edit any cell of a draft proforma line (description, rate, qty, GST, section)."""
    locked_proforma(db, proforma_id)
    li = db.query(ProformaLineItem).populate_existing().filter(ProformaLineItem.id == line_item_id,
                                          ProformaLineItem.proforma_id == proforma_id).first()
    if not li:
        raise HTTPException(status_code=404, detail="Line item not found")
    _require_draft(li.proforma, db, current_user)
    changes = payload.model_dump(exclude_unset=True)
    gst_given = "gst_amount" in changes
    gst_value = changes.pop("gst_amount", None)
    for field, value in changes.items():
        if value is not None and getattr(li, field) != value:
            record_change(db, "proforma_line_items", li.id, field, getattr(li, field), value, current_user.id)
            setattr(li, field, value)
    if gst_given and gst_value is None:
        li.gst_is_actual = False  # back to rate x amount
    li.is_manual = True  # the automatic refresh leaves hand-edited lines alone
    recalc(li, gst_value if gst_given else None)
    sync_gst_difference(db, li.proforma)
    db.commit()
    db.refresh(li.proforma)
    return _to_out(li.proforma)


@router.post("/proformas/{proforma_id}/fill-from-shipment", response_model=FillResult)
def fill_from_shipment(proforma_id: int, db: Session = Depends(get_db),
                       current_user: User = Depends(require_billing_access)):
    """Add every line the shipment knows (Agency, Examination, Customs Duty, Stamp
    Duty, CFS, Royalty for HSS, shipping line per SAC) and refresh the
    document-derived ones; lines edited by hand are left alone. See autofill.py."""
    proforma = locked_proforma(db, proforma_id)
    _require_draft(proforma, db, current_user)
    _require_documents(proforma.shipment)
    added, updated, skipped = sync_proforma(db, proforma, full=True)
    db.commit()
    db.refresh(proforma)
    return FillResult(proforma=_to_out(proforma), added=added, updated=updated, skipped=skipped)


@router.post("/proformas/{proforma_id}/restore", response_model=ProformaOut)
def restore_derived_line(proforma_id: int, payload: RestoreIn, db: Session = Depends(get_db),
                         current_user: User = Depends(require_billing_access)):
    """Bring back a removed document-derived line (Shipping Line, Customs Duty,
    Stamp Duty, CFS, Examination) with the figure from the documents."""
    proforma = locked_proforma(db, proforma_id)
    _require_draft(proforma, db, current_user)
    if not restore_line(db, proforma, payload.key):
        db.rollback()
        raise HTTPException(status_code=400, detail="Nothing to add from the documents for this charge yet "
                                                    "(no invoice / BE amount, or it doesn't apply — e.g. not under examination).")
    record_change(db, "proformas", proforma.id, "restored", None, payload.key, current_user.id)
    db.commit()
    db.refresh(proforma)
    return _to_out(proforma)


@router.get("/proformas/{proforma_id}/invoice")
def get_invoice(proforma_id: int, db: Session = Depends(get_db),
                current_user: User = Depends(require_billing_access)):
    """The proforma laid out as the client's invoice (drives the on-screen view)."""
    return build_invoice(_get_proforma(db, proforma_id))


@router.get("/proformas/{proforma_id}/invoice.{fmt}")
def download_invoice(proforma_id: int, fmt: str, db: Session = Depends(get_db),
                     current_user: User = Depends(require_billing_access)):
    """Excel (.xlsx) or PDF of the invoice, in the template's layout."""
    proforma = _get_proforma(db, proforma_id)
    _require_documents(proforma.shipment)
    if fmt == "xlsx":
        data, media = render_xlsx(build_invoice(proforma)), \
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif fmt == "pdf":
        data, media = render_pdf(build_invoice(proforma)), "application/pdf"
    else:
        raise HTTPException(status_code=404, detail="Use .xlsx or .pdf")
    filename = invoice_filename(proforma, fmt)
    return Response(content=data, media_type=media, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Filename": quote(filename),
        "Access-Control-Expose-Headers": "X-Filename",
    })


@router.get("/proformas/{proforma_id}/history", response_model=list[ProformaSnapshotOut])
def proforma_history(proforma_id: int, db: Session = Depends(get_db),
                     current_user: User = Depends(require_billing_access)):
    """Copies of this invoice as sent, before it was edited again — newest first."""
    return _get_proforma(db, proforma_id).snapshots


@router.get("/proforma-snapshots/{snapshot_id}/invoice.pdf")
def snapshot_pdf(snapshot_id: int, db: Session = Depends(get_db),
                 current_user: User = Depends(require_billing_access)):
    snap = db.get(ProformaSnapshot, snapshot_id)
    if not snap or snap.proforma is None:
        raise HTTPException(status_code=404, detail="Not found")
    filename = invoice_filename(snap.proforma, "pdf").replace(".pdf", f" - as sent {snap.created_at:%d-%m-%Y}.pdf")
    return Response(content=render_pdf(snap.invoice), media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Filename": quote(filename),
        "Access-Control-Expose-Headers": "X-Filename",
    })


def _get_proforma(db: Session, proforma_id: int) -> Proforma:
    proforma = db.query(Proforma).filter(Proforma.id == proforma_id).first()
    if not proforma:
        raise HTTPException(status_code=404, detail="Proforma not found")
    return proforma


@router.delete("/proformas/{proforma_id}/line-items/{line_item_id}", response_model=ProformaOut)
def remove_line_item(
    proforma_id: int,
    line_item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_billing_access),
):
    proforma = locked_proforma(db, proforma_id)
    if not proforma:
        raise HTTPException(status_code=404, detail="Proforma not found")
    line_item = db.query(ProformaLineItem).filter(
        ProformaLineItem.id == line_item_id, ProformaLineItem.proforma_id == proforma_id
    ).first()
    if not line_item:
        raise HTTPException(status_code=404, detail="Line item not found")
    _require_draft(proforma, db, current_user)
    if line_item.charge and line_item.charge.code in DERIVED_CODES:
        proforma.suppressed = sorted(set(proforma.suppressed or []) | {line_key(line_item)})
    proforma.line_items.remove(line_item)
    db.delete(line_item)
    sync_gst_difference(db, proforma)
    db.commit()
    db.refresh(proforma)
    return _to_out(proforma)


@router.patch("/proformas/{proforma_id}", response_model=ProformaOut)
def update_proforma_status(
    proforma_id: int,
    payload: ProformaStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_billing_access),
):
    """Spec §5.2: DRAFT -> SENT; creating a later version supersedes earlier
    ones (left as an explicit follow-up call rather than implied here, same
    pattern as the shipment bill/unbill endpoints)."""
    proforma = locked_proforma(db, proforma_id)
    if not proforma:
        raise HTTPException(status_code=404, detail="Proforma not found")
    changes = payload.model_dump(exclude_unset=True)
    if "bill_rate" in changes or "bill_to_org_id" in changes:
        _require_draft(proforma, db, current_user)
    if changes.get("bill_to_org_id") is not None and not db.get(OrganizationEntry, changes["bill_to_org_id"]):
        raise HTTPException(status_code=404, detail="Organization not found")
    if "bill_rate" in changes:
        # typed rate: anything above the value per kg with a GST difference above zero;
        # cleared: back to the automatic rate
        proforma.bill_rate_manual = changes["bill_rate"] is not None
        if changes["bill_rate"] is not None and proforma.shipment is not None and proforma.shipment.is_hss:
            v = value_summary(proforma)
            old_rate, proforma.bill_rate = proforma.bill_rate, changes["bill_rate"]
            ok = value_summary(proforma)["manual_rate_ok"]
            proforma.bill_rate = old_rate
            if ok is False:
                db.rollback()
                raise HTTPException(status_code=400, detail=(
                    f"Bill rate must be above the value per kg (₹{v['value_per_kg']}) and leave a "
                    f"GST difference above zero (GST input ₹{v['gst_input']})."))
    for field, value in changes.items():
        if field in ("name", "bill_to") and isinstance(value, str):
            value = value.strip() or None
        if getattr(proforma, field) != value:
            record_change(db, "proformas", proforma.id, field, getattr(proforma, field), value, current_user.id)
            setattr(proforma, field, value)
    if "bill_rate" in changes:
        sync_gst_difference(db, proforma)
        partner = _hss_partner(db, proforma)
        if partner is not None and (partner.bill_rate != proforma.bill_rate
                                    or partner.bill_rate_manual != proforma.bill_rate_manual):
            # buyer and seller copies carry the same bill rate (client, 2026-10-07)
            _require_draft(partner, db, current_user)
            record_change(db, "proformas", partner.id, "bill_rate", partner.bill_rate, proforma.bill_rate, current_user.id)
            partner.bill_rate, partner.bill_rate_manual = proforma.bill_rate, proforma.bill_rate_manual
            sync_gst_difference(db, partner)
    sent_now = changes.get("status") == ProformaStatus.SENT
    db.commit()
    if sent_now:  # the version that went to the client: keep its PDF (local + Drive)
        storage.save_pdf(db, "proforma_pdf", proforma.id, f"Invoices/Proformas/{fy_of(date.today())}",
                         invoice_filename(proforma, "pdf"), render_pdf(build_invoice(proforma)))
        db.commit()
    db.refresh(proforma)
    return _to_out(proforma)


@router.delete("/proformas/{proforma_id}", status_code=204)
def delete_draft_proforma(
    proforma_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_billing_access),
):
    """The invoice is never deleted (client, 2026-10-08): every shipment is billed, so its one live invoice
    is edited instead. Kept as a route so an old screen gets a clear answer."""
    proforma = locked_proforma(db, proforma_id)
    if not proforma:
        raise HTTPException(status_code=404, detail="Proforma not found")
    raise HTTPException(status_code=400, detail="The invoice isn't deleted — edit it instead.")


def _hss_partner(db: Session, proforma: Proforma) -> Optional[Proforma]:
    """HSS: the working invoice for the other party (seller <-> buyer)."""
    if proforma.bill_to_role not in ("seller", "buyer"):
        return None
    other = "buyer" if proforma.bill_to_role == "seller" else "seller"
    return (db.query(Proforma).filter(Proforma.shipment_id == proforma.shipment_id, Proforma.bill_to_role == other,
                                      Proforma.status != ProformaStatus.SUPERSEDED)
            .order_by(Proforma.version_number.desc()).first())


def _to_out(proforma: Proforma) -> ProformaOut:
    out = ProformaOut.model_validate(proforma)
    who = copy_for(proforma)
    out.party = who[4:] if who else None  # "For Mahrishi" -> "Mahrishi"
    out.revisions = len(proforma.snapshots)
    out.line_items = sorted(out.line_items, key=lambda li: li.id)
    out.grand_total = clarus_total(proforma)  # payable to Clarus (see build.in_clarus_total)
    out.match_total = match_total(proforma)
    return out


# --- proforma register: every proforma across shipments (the Invoices page, client 2026-09-30) ---

def _proforma_rows(db: Session, fy: Optional[str], month: Optional[str], status: Optional[str],
                   client: Optional[str], q: Optional[str], ids: Optional[str] = None) -> list[Proforma]:
    query = db.query(Proforma)
    if ids:
        query = query.filter(Proforma.id.in_([int(x) for x in ids.split(",") if x.strip().isdigit()]))
    if status in ("draft", "sent", "superseded"):
        query = query.filter(Proforma.status == ProformaStatus(status))
    out = []
    for p in query.order_by(Proforma.created_at.desc(), Proforma.id.desc()).all():
        d = p.created_at.date() if p.created_at else None
        if fy and (not d or fy_of(d) != fy):
            continue
        if month and (not d or f"{d:%Y-%m}" != month):
            continue
        s = p.shipment
        if s is None:  # its shipment is gone: nothing to list it under
            continue
        party = (p.bill_to or be_importer_name(s) or "") if s else (p.bill_to or "")
        if client and client.lower() not in party.lower():
            continue
        if q and q.lower() not in " ".join(str(x or "") for x in (s.job, s.mbl, s.be_no, p.name)).lower():
            continue
        out.append(p)
    return out


@router.get("/proformas")
def proforma_register(fy: Optional[str] = None, month: Optional[str] = None, status: Optional[str] = None,
                      client: Optional[str] = None, q: Optional[str] = None, db: Session = Depends(get_db)):
    rows = []
    for p in _proforma_rows(db, fy, month, status, client, q):
        inv = build_invoice(p)
        s = p.shipment
        rows.append({
            "id": p.id, "shipment_id": p.shipment_id, "job": s.job, "mbl": s.mbl, "be_no": s.be_no,
            "version": p.version_number, "name": p.name, "status": p.status.value, "role": p.bill_to_role,
            "bill_to": inv["bill_to"]["name"], "date": p.created_at.date().isoformat() if p.created_at else None,
            "grand_total": inv["grand_total"],
        })
    fys = sorted({fy_of(p.created_at.date()) for p in db.query(Proforma).all() if p.created_at}, reverse=True)
    return {"proformas": rows, "financial_years": fys}


@router.get("/proformas/export.pdf")
def export_proformas(ids: str, db: Session = Depends(get_db)):
    """The chosen proformas in one PDF (one per page)."""
    import io

    import pypdfium2

    rows = _proforma_rows(db, None, None, None, None, None, ids=ids)
    if not rows:
        raise HTTPException(status_code=404, detail="No proformas chosen")
    out = pypdfium2.PdfDocument.new()
    for p in rows:
        out.import_pages(pypdfium2.PdfDocument(render_pdf(build_invoice(p))))
    buf = io.BytesIO()
    out.save(buf)
    filename = f"Proformas ({len(rows)}).pdf"
    return Response(content=buf.getvalue(), media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Filename": quote(filename), "Access-Control-Expose-Headers": "X-Filename",
    })
