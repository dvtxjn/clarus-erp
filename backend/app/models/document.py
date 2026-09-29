from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Enum as SAEnum, Boolean, JSON, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.soft_delete import SoftDeleteMixin
from app.core.enums import DocumentType


class HSCode(Base):
    """
    Spec §3.1: "An HS-code management interface where new HS codes can be
    added, each with its own configurable list of required documents."
    Only one HS code (tyre) is populated at launch — see seed data.
    """
    __tablename__ = "hs_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True, nullable=False)
    description = Column(String, nullable=False)

    required_documents = relationship("RequiredDocument", back_populates="hs_code", cascade="all, delete-orphan")


class RequiredDocument(Base):
    """
    One row per (HS code, document type) that's required for that HS code.
    When a shipment is tagged with an HS code, this drives the checklist
    that pops up in the Document Manager (spec §3.1).
    """
    __tablename__ = "required_documents"

    id = Column(Integer, primary_key=True, index=True)
    hs_code_id = Column(Integer, ForeignKey("hs_codes.id"), nullable=False)
    document_type = Column(SAEnum(DocumentType, native_enum=False, length=40), nullable=False)
    # optional = listed on the checklist but a missing one isn't flagged
    # (e.g. Empty Letter — often comes inside the DO letter)
    optional = Column(Boolean, nullable=False, default=False, server_default="0")

    hs_code = relationship("HSCode", back_populates="required_documents")


class ShipmentDocument(SoftDeleteMixin, Base):
    """
    A single uploaded PDF, tagged with a document type, auto-renamed per
    the naming syntax in spec §3.2, and (where a mapping exists — see
    DOC_TYPE_TRACKER_FIELD_MAP in extraction/tracker_sync.py) triggers an
    auto-update on the parent Shipment's tracker fields.
    """
    __tablename__ = "shipment_documents"

    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id"), nullable=False)

    document_type = Column(SAEnum(DocumentType, native_enum=False, length=40), nullable=False)

    original_filename = Column(String, nullable=False)
    generated_filename = Column(String, nullable=False)  # per naming syntax, spec §3.2
    file_path = Column(String, nullable=False)  # storage location

    # Set True once the doc-type -> tracker-field auto-update has run
    # (spec §3.3). Kept as a flag so re-processing doesn't double-apply.
    tracker_sync_applied = Column(Boolean, default=False, nullable=False)
    # What was read from the PDF and what it changed on the shipment, e.g.
    # {"fields": {...}, "updated": ["be_no", ...], "notes": ["BE no on PDF differs..."]}
    extraction = Column(JSON, nullable=True)
    # set when the file was picked from Google Drive instead of uploaded
    drive_file_id = Column(String, nullable=True)
    drive_link = Column(String, nullable=True)
    # STORAGE_BACKEND=drive: the server's copy in the Shared Drive failed to save yet
    # (the local file is kept; a background job retries). drive_error says why.
    drive_sync_pending = Column(Boolean, nullable=False, default=False, server_default="0")
    # Picked from the shipment's own Drive folder (made by staff): the ERP links to that
    # original — it never uploads a second copy or renames it.
    drive_picked = Column(Boolean, nullable=False, default=False, server_default="0")
    # digital | partly | scanned | unreadable — can the ERP read text from it (extraction/pdf_kind.py)
    pdf_kind = Column(String, nullable=True)
    drive_error = Column(String, nullable=True)

    # CFS proforma / tax invoice amounts — read from the PDF, correctable by hand.
    # amount_total is always before-tax + GST. The shipment's CFS figures are
    # the sum over its invoices (see extraction/cfs_totals.py).
    amount_before_tax = Column(Numeric(14, 2), nullable=True)
    gst_amount = Column(Numeric(14, 2), nullable=True)
    amount_total = Column(Numeric(14, 2), nullable=True)
    amounts_edited = Column(Boolean, nullable=False, default=False, server_default="0")
    # Shipping line invoices: the part that is the proforma's cost inclusion.
    # Client rule: only charges billed in INR (a foreign-currency charge, e.g. USD
    # freight, isn't a destination charge). None = the whole invoice counts.
    cost_before_tax = Column(Numeric(14, 2), nullable=True)
    cost_gst = Column(Numeric(14, 2), nullable=True)
    cost_excluded = Column(JSON, nullable=True)  # indices into extraction.fields.charges left out
    cost_manual = Column(Boolean, nullable=False, default=False, server_default="0")  # figure typed by hand

    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    shipment = relationship("Shipment", back_populates="documents")
