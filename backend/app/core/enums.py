"""
Central enums for the ERP. Kept in one place because several of these
(status pipeline, roles, document types) are referenced across multiple
models and routers.

Spec references: ERP_Spec.md §2.3 (status pipeline), §2.4 (roles),
§3.1 (document taxonomy).
"""
import enum


class ShipmentStatus(str, enum.Enum):
    """
    Linear v1 status pipeline (spec §2.3). Deliberately NOT heavily branched —
    exceptions are handled via the `is_stuck` flag + `remarks` field on the
    Shipment model instead of extra pipeline states.

    IMPORTANT distinction (spec §2.3):
    - OOC_DONE is set automatically the moment an OOC Bill of Entry PDF is
      uploaded & tagged (document-driven, not manual).
    - CLEARED is only set when Gatepass is done (container has physically
      exited for delivery at the yard) — a separate, later, manual event.
    """
    TO_BE_FILED = "to_be_filed"
    IGM_FILED = "igm_filed"
    BE_FILED = "be_filed"
    BE_ASSESSED = "be_assessed"
    DUTY_PAID = "duty_paid"
    UNDER_OOC = "under_ooc"
    OOC_DONE = "ooc_done"
    CLEARED = "cleared"
    BILLED = "billed"  # terminal state — shipment archived, see spec §5.5


class UserRole(str, enum.Enum):
    """Spec §2.4. Admin has full permissions; the other three follow the
    same base permission set (view/add, delete needs admin approval) unless
    a more granular permission matrix is defined later."""
    ADMIN = "admin"
    IMPORT_MANAGER = "import_manager"
    EXPORT_MANAGER = "export_manager"
    ACCOUNTANT = "accountant"


class DocumentType(str, enum.Enum):
    """
    Base document taxonomy (spec §3.1). This is the starting set for the
    tyre HS code — the HSCode/RequiredDocument tables (see models/document.py)
    are what make this extensible per HS code without a code change, per
    the spec's explicit requirement.
    """
    CFS_PROFORMA_INVOICE = "cfs_proforma_invoice"
    CFS_TAX_INVOICE = "cfs_tax_invoice"
    ASSESSED_BILL_OF_ENTRY = "assessed_bill_of_entry"
    OOC_BILL_OF_ENTRY = "ooc_bill_of_entry"
    GATEPASS_BILL_OF_ENTRY = "gatepass_bill_of_entry"
    BL_COPY = "bl_copy"
    HBL_COPY = "hbl_copy"
    COMMERCIAL_INVOICE = "commercial_invoice"  # the supplier's invoice — one of the key import documents
    PACKING_LIST = "packing_list"
    INSURANCE = "insurance"
    # Shipping line destination charges (imports) — the proforma's "cost inclusion"
    # (the client pays the line directly ~95% of the time). Tax invoice keeps its old value.
    SHIPPING_LINE_INVOICE = "shipping_line_invoice"  # tax invoice
    SHIPPING_LINE_PROFORMA = "shipping_line_proforma"
    SHIPPING_LINE_RECEIPT = "shipping_line_receipt"  # what was actually paid to the line
    CFS_RECEIPT = "cfs_receipt"  # what was actually paid to the CFS
    DO_LETTER = "do_letter"
    EMPTY_LETTER = "empty_letter"
    DO_EMPTY_LETTER = "do_empty_letter"  # DO + Empty letter in one file; satisfies both
    HSS_AGREEMENT = "hss_agreement"
    STAMP_DUTY = "stamp_duty"
    HSS_STAMP_DUTY = "hss_stamp_duty"  # legacy (now two separate documents) — kept for old uploads
    CERTIFICATE_OF_ORIGIN = "certificate_of_origin"
    FTA_CERTIFICATE_OF_ORIGIN = "fta_certificate_of_origin"
    FORM_6_9 = "form_6_9"  # Form 6 & Form 9 come as one merged document
    FORM_6 = "form_6"  # legacy
    FORM_9 = "form_9"  # legacy
    OTHER = "other"


class ChargeCategory(str, enum.Enum):
    """Section of the proforma a charge goes in (client's invoice template).
    SERVICE = "Billed by Clarus" (our fees, our GST); REIMBURSEMENT = "at actuals"
    (paid on the client's behalf, carrying the actual GST paid); COST_INCLUSION =
    shown for reference (shipping line), not part of the total payable to Clarus.
    Fixed per charge where the client said so: see invoice.build.FIXED_SECTIONS."""
    SERVICE = "service"
    REIMBURSEMENT = "reimbursement"
    ROYALTY = "royalty"  # HSS royalty: the seller pays it to the buyer, not a Clarus charge (client, 2026-09-28)
    COST_INCLUSION = "cost_inclusion"


class ChargeCalculationBasis(str, enum.Enum):
    """Spec §5.4/§5.6 — the three patterns used in the reference tool."""
    FLAT = "flat"
    PER_CONTAINER = "per_container"
    PER_KG = "per_kg"


class ProformaStatus(str, enum.Enum):
    """Spec §5.2 — versioning: each revision is a new record, not an overwrite."""
    DRAFT = "draft"
    SENT = "sent"
    SUPERSEDED = "superseded"
