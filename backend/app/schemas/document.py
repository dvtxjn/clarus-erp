from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from app.core.enums import DocumentType


class ShipmentDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipment_id: int
    document_type: DocumentType
    original_filename: str
    generated_filename: str
    file_path: str
    tracker_sync_applied: bool
    uploaded_at: datetime
    # {"fields": what was read, "updated": [field labels changed], "notes": [warnings]}
    extraction: Optional[dict] = None
    drive_file_id: Optional[str] = None
    drive_link: Optional[str] = None
    pdf_kind: Optional[str] = None  # digital | partly | scanned | unreadable
    drive_picked: bool = False  # linked to a file already in the shipment's Drive folder
    drive_sync_pending: bool = False  # not saved in the Shared Drive yet (retried every 5 min)
    drive_error: Optional[str] = None
    drive_folder_id: Optional[str] = None  # saved to this folder instead of the shipment's linked one
    # CFS invoices only
    amount_before_tax: Optional[Decimal] = None
    gst_amount: Optional[Decimal] = None
    amount_total: Optional[Decimal] = None
    amounts_edited: bool = False
    # Shipping line invoices: cost inclusion part (None = whole invoice)
    cost_before_tax: Optional[Decimal] = None
    cost_gst: Optional[Decimal] = None
    cost_excluded: Optional[list[int]] = None
    cost_manual: bool = False


class CostInclusionIn(BaseModel):
    """Shipping line invoice -> cost inclusion. Either `excluded` (charge-line
    indices to leave out), or `before_tax` + `gst` typed by hand, or `reset`
    (back to the rule: INR charges that aren't freight)."""
    excluded: Optional[list[int]] = None
    before_tax: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    gst: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    reset: bool = False


class InvoiceAmountsIn(BaseModel):
    """Correct a CFS invoice's figures; the total is always before-tax + GST."""
    amount_before_tax: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    gst_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)


class HSCodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    description: str
    required_document_types: list[DocumentType] = []

    @classmethod
    def from_orm_with_docs(cls, hs_code) -> "HSCodeOut":
        return cls(
            id=hs_code.id,
            code=hs_code.code,
            description=hs_code.description,
            required_document_types=[rd.document_type for rd in hs_code.required_documents],
        )


class DocumentChecklistItem(BaseModel):
    """One row in the Document Manager checklist (spec §3.1): whether a
    required document type has been uploaded yet for this shipment, and
    which uploaded document (if any) satisfies it."""

    document_type: DocumentType
    required: bool
    optional: bool = False
    uploaded: bool
    document: Optional[ShipmentDocumentOut] = None  # first one (kept for older clients)
    documents: list[ShipmentDocumentOut] = []  # every file counting for this row, e.g. several CFS invoices
