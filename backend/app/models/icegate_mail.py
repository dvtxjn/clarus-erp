from sqlalchemy import JSON, Boolean, Column, Date, DateTime, ForeignKey, Integer, LargeBinary, String, Text, func

from app.core.database import Base


class IcegateMail(Base):
    """
    One ICEGATE e-mail, read (client, 2026-09-30): what it says, which shipment it belongs to, and what it
    changed. Kept for the shipment's customs timeline; B/E Negative Ack / Query / failed filings stay in
    "Needs attention" until resolved. Never deleted.
    """
    __tablename__ = "icegate_mails"

    id = Column(Integer, primary_key=True, index=True)
    fingerprint = Column(String(64), unique=True, nullable=False)  # sha256 of the mail: the same mail is read once
    message_id = Column(String, nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=True, index=True)
    kind = Column(String(40), nullable=False, index=True)
    label = Column(String, nullable=False)
    subject = Column(String, nullable=True)
    summary = Column(Text, nullable=True)
    be_no = Column(String, nullable=True, index=True)
    be_date = Column(Date, nullable=True)
    job_no = Column(String, nullable=True, index=True)
    port = Column(String, nullable=True)
    mbl = Column(String, nullable=True)
    detail = Column(JSON, nullable=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id"), nullable=True, index=True)
    applied = Column(Boolean, nullable=False, default=False)   # its changes were made on the shipment
    notes = Column(JSON, nullable=True)                         # what applying it did / found
    pdf_name = Column(String, nullable=True)
    pdf = Column(LargeBinary, nullable=True)                    # BE / OOC / gatepass copy waiting for its shipment
    document_id = Column(Integer, ForeignKey("shipment_documents.id"), nullable=True)
    attention = Column(Boolean, nullable=False, default=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_note = Column(String, nullable=True)
    imported_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
