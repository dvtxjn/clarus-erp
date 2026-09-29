from sqlalchemy import (
    Boolean,
    Column, Integer, String, Numeric, DateTime, ForeignKey, Enum as SAEnum, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.core.enums import ChargeCategory, ProformaStatus


class Proforma(Base):
    """
    Spec §5.2: every revision is a NEW record against the same shipment —
    full version history retained, never overwritten. Spec §5.1's
    auto-extracted fields are snapshotted into `extracted_data` at creation
    time so a later re-extraction doesn't silently change a past version.
    """
    __tablename__ = "proformas"

    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id"), nullable=False)

    version_number = Column(Integer, nullable=False)
    name = Column(String, nullable=True)  # user's own label for the version, e.g. "Revised after exam"
    # Bill To = the BE importer (for HSS: the buyer, after the '-')
    bill_to = Column(String, nullable=True)
    # HSS: whose copy this is — "seller" | "buyer"; None for normal shipments
    bill_to_role = Column(String, nullable=True)
    # Organization repository entry whose details go in the Bill To block
    # (None = matched by name at render time)
    bill_to_org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    # HSS: sale rate per kg on the HSS bill; drives the GST Difference line
    bill_rate = Column(Numeric(12, 2), nullable=True)
    # document-derived lines someone removed (e.g. "CFS", "DO:996711") — the automatic
    # refresh doesn't put them back; "Fill / refresh from shipment" clears this
    suppressed = Column(JSON, nullable=True)
    status = Column(SAEnum(ProformaStatus, native_enum=False, length=40), default=ProformaStatus.DRAFT, nullable=False)

    # Snapshot of BE/CFS-extracted fields at time of this version (spec §5.1):
    # total duty, container count, HBL, MBL, consignee, BE no/date, etc.
    extracted_data = Column(JSON, nullable=True)

    generated_filename = Column(String, nullable=True)  # per naming syntax, spec §5.5
    file_path = Column(String, nullable=True)

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    shipment = relationship("Shipment", back_populates="proformas")
    line_items = relationship("ProformaLineItem", back_populates="proforma", cascade="all, delete-orphan")


class ProformaLineItem(Base):
    """
    Spec §5.3 (dynamic charge selection — the important correction): a
    proforma can have any number of these, any combination of charges from
    the charge master. NOT a fixed set of columns/rows like the reference
    tool's Excel template.
    """
    __tablename__ = "proforma_line_items"

    id = Column(Integer, primary_key=True, index=True)
    proforma_id = Column(Integer, ForeignKey("proformas.id"), nullable=False)
    charge_master_id = Column(Integer, ForeignKey("charge_master_entries.id"), nullable=False)

    description = Column(String, nullable=True)  # optional override of the charge's default name
    rate = Column(Numeric(12, 2), nullable=False)
    quantity = Column(Numeric(10, 2), nullable=False, default=1)  # e.g. container count, kg
    amount = Column(Numeric(12, 2), nullable=False)  # rate * quantity, pre-GST

    sac_code = Column(String, nullable=False)  # copied from charge master at time of use (audit-safe)
    gst_rate = Column(Numeric(5, 2), nullable=False)
    gst_amount = Column(Numeric(12, 2), nullable=False)
    total = Column(Numeric(12, 2), nullable=False)  # amount + gst_amount
    # invoice section (copied from the charge master; can be changed per line)
    category = Column(SAEnum(ChargeCategory, native_enum=False, length=40), nullable=False, default=ChargeCategory.SERVICE,
                      server_default=ChargeCategory.SERVICE.name)
    # True when GST is an actual figure (e.g. IGST on duty, GST on the CFS invoice)
    # rather than gst_rate x amount
    gst_is_actual = Column(Boolean, nullable=False, default=False, server_default="0")
    sort_order = Column(Integer, nullable=False, default=0, server_default="0")
    # edited by hand -> the automatic refresh leaves it alone
    is_manual = Column(Boolean, nullable=False, default=False, server_default="0")

    proforma = relationship("Proforma", back_populates="line_items")
    charge = relationship("ChargeMasterEntry")
