from sqlalchemy import (
    Column, Integer, String, Boolean, Date, DateTime, Text, ForeignKey, JSON, Numeric,
    Enum as SAEnum
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.sql.expression import false as sa_false
from datetime import date, datetime
from typing import Optional
from decimal import Decimal, ROUND_HALF_UP

from app.core.database import Base
from app.models.soft_delete import SoftDeleteMixin
from app.core.enums import ShipmentStatus


# A shipment is cleared only when it has a Cleared Date AND all five of these
# are ticked. A Cleared Date with anything missing is an exception: it stays
# with the ongoing shipments for someone to sort out by hand.
CLEARANCE_FLAGS = (
    ("duty_paid", "Duty"),
    ("cfs_inv_received", "CFS Inv"),
    ("line_paid", "Line"),
    ("ooc", "OOC"),
    ("do", "DO"),
)

def split_hss(consignee):
    """'HKR - Mahrishi' -> ('HKR', 'Mahrishi'); None if the name has no '-'.
    Client rule: any importer name with a '-' in it is an HSS shipment."""
    if not consignee or "-" not in consignee:
        return None
    seller, buyer = (p.strip() for p in consignee.split("-", 1))
    return (seller, buyer) if seller and buyer else None


# TDS we deduct when paying a CFS invoice (on the basic value, before GST)
CFS_TDS_RATE = Decimal("0.02")


class Shipment(SoftDeleteMixin, Base):
    """
    Core shipment record. Field list is the confirmed 26-field set from
    spec §2.1/§2.2, plus a few structural additions called out explicitly
    in the spec (HBL own column, HS code FK, port for scoping, stuck flag).

    Primary tracking keys: MBL + Job (+ HBL where applicable).
    Secondary tracking keys: BE Number + BE Date.
    """
    __tablename__ = "shipments"

    id = Column(Integer, primary_key=True, index=True)

    # --- Primary/secondary tracking keys (spec §2.1) ---
    job = Column(String, index=True, nullable=False)
    mbl = Column(String, index=True, nullable=False)
    hbl = Column(String, index=True, nullable=True)  # spec: own column; multi-HBL
    # per MBL is architecturally possible via a separate table later but is
    # explicitly not a v1 priority (client: "one in a million" case).
    be_no = Column(String, index=True, nullable=True)
    be_dt = Column(Date, nullable=True)

    # --- Core descriptive fields ---
    be_description = Column(String, nullable=True)
    eta = Column(Date, nullable=True)
    # the ETA is a deadline, not just an expected date — the "d" on the ETA (client, 2026-09-29)
    eta_is_deadline = Column(Boolean, default=False, nullable=False, server_default=sa_false())
    inw = Column(String, nullable=True)  # inward — format TBD with client, kept as string for now
    day = Column(String, nullable=True)
    license = Column(String, nullable=True)
    client = Column(String, nullable=True)
    consignee = Column(String, nullable=True)
    pod = Column(String, nullable=True)  # Port of Discharge
    container_status = Column(String, nullable=True)
    cfs = Column(String, nullable=True)
    container = Column(String, nullable=True)
    gross_wt = Column(String, nullable=True)
    poc = Column(String, nullable=True)
    cleared_date = Column(Date, nullable=True)
    igm = Column(String, nullable=True)
    delivery_status = Column(String, nullable=True)

    # --- Extra columns from the client's live tracker sheet ---
    remark = Column(String, nullable=True)  # sheet's short "remark" (e.g. OOC/SUP); `remarks` is the free-text why
    mbl_date = Column(Date, nullable=True)
    hbl_date = Column(Date, nullable=True)
    gw = Column(String, nullable=True)
    total_pkg = Column(String, nullable=True)
    pkg_code = Column(String, nullable=True)
    line_no = Column(String, nullable=True)
    igm_date = Column(Date, nullable=True)
    voyage = Column(String, nullable=True)
    cont = Column(String, nullable=True)
    shipping_line = Column(String, nullable=True)

    # --- Read from uploaded documents (Assessed/OOC BE, CFS invoice) ---
    assessable_value = Column(Numeric(14, 2), nullable=True)
    igst_amount = Column(Numeric(14, 2), nullable=True)
    duty_amount = Column(Numeric(14, 2), nullable=True)  # BE "TOT. AMOUNT" (duty payable)
    cfs_amount_before_tax = Column(Numeric(14, 2), nullable=True)
    cfs_gst_amount = Column(Numeric(14, 2), nullable=True)
    cfs_amount_total = Column(Numeric(14, 2), nullable=True)
    # sum of the shipping line destination charges invoices (proforma "cost inclusion")
    line_amount_before_tax = Column(Numeric(14, 2), nullable=True)
    line_gst_amount = Column(Numeric(14, 2), nullable=True)
    line_amount_total = Column(Numeric(14, 2), nullable=True)
    ooc_date = Column(Date, nullable=True)
    under_examination = Column(Boolean, nullable=True)  # None = not known yet (no OOC copy read)
    examination_at = Column(String, nullable=True)  # as printed on the OOC copy, e.g. "03/09/2026 14:22"

    # values for user-created tracker columns: {column key: value}
    custom_fields = Column(JSON, nullable=False, default=dict, server_default="{}")
    # ICEGATE read-out (app/igm/refresh.py): sea IGM extras (vessel, gateway IGM for inland) and, for inland
    # shipments, the FPOD ICD BL details not already in the IGM fields + any differences between the two
    icegate = Column(JSON, nullable=True)

    # --- Yes/No tracker flags (spec §2.1 — auto-updated by document upload
    # per §3.3 wherever a mapping exists) ---
    duty_paid = Column(Boolean, default=False, nullable=False)
    cfs_inv_received = Column(Boolean, default=False, nullable=False)
    line_paid = Column(Boolean, default=False, nullable=False)
    ooc = Column(Boolean, default=False, nullable=False)
    do = Column(Boolean, default=False, nullable=False)

    # --- CFS payment & TDS ---
    cfs_paid_by_us = Column(Boolean, default=False, nullable=False, server_default="0")  # not every client's CFS is paid by us
    # Shipping line destination charges are normally paid by the client directly
    # (-> proforma "Cost Inclusion"); when we pay them they're a reimbursement.
    line_paid_by_us = Column(Boolean, default=False, nullable=False, server_default="0")
    # Shipping line invoices in the proforma's cost inclusion: None = auto (follow the
    # organisation's setting, e.g. Harekrishna Rubber: not included), "include" / "exclude" by hand
    line_cost_inclusion = Column(String, nullable=True)
    # set when a tracker CSV import doesn't contain this shipment (flagged, never deleted)
    missing_from_sheet_at = Column(DateTime, nullable=True)
    # CFS paid by us goes on the proforma either as a "reimbursement" (at actuals,
    # the CFS invoice's own GST) or "taxable" (Billed by Clarus, our 18% GST on the basic)
    cfs_billed_as = Column(String, default="reimbursement", nullable=False, server_default="reimbursement")
    tds_deducted = Column(Boolean, default=False, nullable=False, server_default="0")  # TDS cut on the shipment
    tds_on_cfs = Column(Boolean, default=False, nullable=False, server_default="0")  # we cut TDS when paying the CFS

    # --- HSS (high sea sale): consignee "SELLER - BUYER"; each party gets its own invoice ---
    is_hss = Column(Boolean, default=False, nullable=False, server_default="0")
    hss_seller = Column(String, nullable=True)
    hss_buyer = Column(String, nullable=True)

    # --- Google Drive folder the shipment's documents are saved into ---
    drive_folder_id = Column(String, nullable=True)
    drive_folder_link = Column(String, nullable=True)

    # --- Remarks (spec §2.1/§2.3 — "Remark"/"Remarks" merged into one field,
    # doubles as the "why is this stuck" free-text field) ---
    remarks = Column(Text, nullable=True)
    # FTA certificate no / notes — shown as a small "FTA" button on the MBL (client, 2026-09-29)
    fta_info = Column(Text, nullable=True)
    is_stuck = Column(Boolean, default=False, nullable=False)

    # --- Status pipeline (spec §2.3) ---
    status = Column(SAEnum(ShipmentStatus, native_enum=False, length=40), default=ShipmentStatus.TO_BE_FILED, nullable=False, index=True)

    # --- Port scoping (spec §2.4) ---
    port = Column(String, nullable=True, index=True)

    # --- HS code (spec §3.1 — drives required-document checklist) ---
    hs_code_id = Column(Integer, ForeignKey("hs_codes.id"), nullable=True)
    hs_code = relationship("HSCode")

    # --- Billing/archive state (spec §5.5) ---
    is_billed = Column(Boolean, default=False, nullable=False)
    billed_at = Column(DateTime(timezone=True), nullable=True)
    is_archived = Column(Boolean, default=False, nullable=False)  # moved out of live tracker once billed

    # --- Audit ---
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    # Bumped by SQLAlchemy on every write; a write based on a stale copy fails
    # (StaleDataError -> 409) instead of silently overwriting (launch Phase 2).
    version = Column(Integer, nullable=False, default=1, server_default="1")
    __mapper_args__ = {"version_id_col": version}

    documents = relationship("ShipmentDocument", back_populates="shipment", cascade="all, delete-orphan")
    proformas = relationship("Proforma", back_populates="shipment", cascade="all, delete-orphan")

    @property
    def line_from_bl(self) -> Optional[dict]:
        """Shipping line worked out from the MBL's format (app/liners.py) — never stored."""
        from app.liners import identify
        return identify(self.mbl)

    @property
    def days(self) -> str:
        """The sheet's Day formula, referencing the inward date:
        blank/not a date -> 'Pending'; otherwise diff = today - INW, counted
        inclusively (+1) when INW is today or past, left as-is (negative) when
        it's in the future; '1 day' vs 'N days'."""
        for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
            try:
                inw = datetime.strptime((self.inw or "").strip(), fmt).date()
                break
            except ValueError:
                continue
        else:
            return "Pending"
        diff = (date.today() - inw).days
        adj = diff + 1 if diff >= 0 else diff
        return f"{adj} {'day' if abs(adj) == 1 else 'days'}"

    # --- CFS payment (only when we pay the CFS; otherwise we just pass the invoice on) ---
    @property
    def cfs_tds_amount(self) -> Optional[Decimal]:
        """2% of the CFS basic value, when we pay the CFS and cut TDS on it."""
        if not (self.cfs_paid_by_us and self.tds_on_cfs) or self.cfs_amount_before_tax is None:
            return None
        return (Decimal(self.cfs_amount_before_tax) * CFS_TDS_RATE).quantize(Decimal("0.01"), ROUND_HALF_UP)

    @property
    def cfs_payment_after_tds(self) -> Optional[Decimal]:
        """BASIC VALUE + GST - 2% of BASIC VALUE (TDS) = what we actually pay the CFS."""
        if not self.cfs_paid_by_us or self.cfs_amount_before_tax is None:
            return None
        basic = Decimal(self.cfs_amount_before_tax)
        gst = Decimal(self.cfs_gst_amount or 0)
        return (basic + gst - (self.cfs_tds_amount or 0)).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # --- Clearance ---
    @property
    def missing_for_clearance(self) -> list:
        """Checklist items still unticked (labels), for shipments that have a Cleared Date."""
        return [label for field, label in CLEARANCE_FLAGS if not getattr(self, field)]

    @property
    def is_fully_cleared(self) -> bool:
        return self.cleared_date is not None and not self.missing_for_clearance

    def apply_hss_from_consignee(self) -> None:
        """Set HSS + seller/buyer from the consignee name ('SELLER - BUYER')."""
        parties = split_hss(self.consignee)
        self.is_hss = parties is not None
        self.hss_seller, self.hss_buyer = parties if parties else (None, None)

