from sqlalchemy import JSON, Boolean, Column, Integer, String

from app.core.database import Base


class Licence(Base):
    """
    A licence always belongs to the buyer / BE importer. Its charge rates fill new
    proformas automatically (client, 2026-09-28). `rates` rows:
        {"code": charge code, "seller": optional, "port": optional,
         "per_container": ₹, "per_kg": ₹, "flat": ₹, "category": optional section}
    For each charge the most specific matching row wins (seller + port > seller >
    port > neither). On HSS shipments the seller is the HSS seller (rates follow
    the seller). is_active False = licence closed ("done and dusted").
    """
    __tablename__ = "licences"

    id = Column(Integer, primary_key=True)
    number = Column(String, unique=True, nullable=False, index=True)
    importer_name = Column(String, nullable=True)
    rates = Column(JSON, nullable=False, default=list)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    notes = Column(String, nullable=True)
