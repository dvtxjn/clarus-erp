from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.soft_delete import SoftDeleteMixin


class Payment(SoftDeleteMixin, Base):
    """Money received from a client (client, 2026-09-30, P1). Split over their issued invoices by
    PaymentAllocation; whatever isn't allocated stays on account. Never removed (soft delete)."""
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    received_on = Column(Date, nullable=False)
    party = Column(String, nullable=False)          # the client, as on the invoices
    party_gstin = Column(String, nullable=True)
    amount = Column(Numeric(14, 2), nullable=False)  # what reached the bank
    mode = Column(String, nullable=True)             # NEFT / RTGS / Cheque / UPI / Cash / Other
    reference = Column(String, nullable=True)        # UTR / cheque no.
    notes = Column(String, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    allocations = relationship("PaymentAllocation", back_populates="payment", cascade="all, delete-orphan")


class PaymentAllocation(Base):
    """Part of a payment set against one invoice; `tds` = tax the client deducted on it (settles it too)."""
    __tablename__ = "payment_allocations"

    id = Column(Integer, primary_key=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=False, index=True)
    final_invoice_id = Column(Integer, ForeignKey("final_invoices.id"), nullable=False, index=True)
    amount = Column(Numeric(14, 2), nullable=False, default=0)
    tds = Column(Numeric(14, 2), nullable=False, default=0)

    payment = relationship("Payment", back_populates="allocations")
    invoice = relationship("FinalInvoice")
