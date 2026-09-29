from datetime import datetime

from sqlalchemy import JSON, Column, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.soft_delete import SoftDeleteMixin


class FinalInvoice(SoftDeleteMixin, Base):
    """
    The invoice that goes to the client and the authorities, made from a proforma
    (client, 2026-09-28). Two kinds, numbered as a pair in one series per financial year:
      tax            "CL/<n>/<FY>"     — only the charges Billed by Clarus (taxable, our GST)
      reimbursement  "RI/CL/<n>/<FY>"  — only the charges paid by us (pure agent, no GST)
    Royalty and Cost Inclusion are not invoiced by Clarus.
    Draft: every field can be overridden by hand (audit-logged). Issue: the number is
    given and the invoice locks (only IRN / ACK can still be filled in). Cancel: kept,
    number never reused.
    """
    __tablename__ = "final_invoices"

    id = Column(Integer, primary_key=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id"), nullable=False, index=True)
    proforma_id = Column(Integer, ForeignKey("proformas.id"), nullable=True)
    kind = Column(String, nullable=False)  # "tax" | "reimbursement"
    status = Column(String, nullable=False, default="draft")  # draft | issued | cancelled
    seq = Column(Integer, nullable=True)
    fy = Column(String, nullable=True)  # "26-27"
    number = Column(String, nullable=True, unique=True)
    invoice_date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)
    customer = Column(JSON, nullable=False, default=dict)  # name, address, pan, gstin, state_code, state_name
    header = Column(JSON, nullable=False, default=dict)  # job no, BE / MBL / HBL / vessel … (see final.HEADER_FIELDS)
    lines = Column(JSON, nullable=False, default=list)  # description, sub_description, sac, tax_type, non_gst_value, taxable_value, gst_rate
    advance_received = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    remarks = Column(String, nullable=True)
    irn = Column(String, nullable=True)
    ack_no = Column(String, nullable=True)
    ack_date = Column(String, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    issued_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    cancelled_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    cancel_reason = Column(String, nullable=True)

    shipment = relationship("Shipment")


class InvoiceCounter(Base):
    """Next invoice number per financial year (settable: the series continues from
    the client's existing invoices)."""
    __tablename__ = "invoice_counters"

    fy = Column(String, primary_key=True)
    next_seq = Column(Integer, nullable=False)
