from sqlalchemy import JSON, Boolean, Column, Integer, String

from app.core.database import Base


class PricingRule(Base):
    """
    HSS pricing rule: for shipments whose BE importer matches, the lines Fill
    puts on the seller copy or the buyer copy. Each line:
        {"code": charge code, "per_container": ₹, "per_kg": ₹, "flat": ₹, "category": optional section}
    amount = per_container x containers + per_kg x BE gross weight (kg) + flat.
    E.g. Mahrishi (client, 2026-09-28): seller copy Royalty 1/kg + Other Charges
    20,000/container; buyer copy Royalty 0.75/kg + Other Charges 20,000/container
    + 0.25/kg — same invoice total on both copies.
    """
    __tablename__ = "pricing_rules"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    importer_name = Column(String, nullable=False)  # buyer = BE importer (matched loosely, like the org repository)
    seller_name = Column(String, nullable=True)  # HSS seller; None = any seller (a seller-specific rule wins)
    bill_to_role = Column(String, nullable=False)  # "seller" | "buyer"
    lines = Column(JSON, nullable=False, default=list)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
