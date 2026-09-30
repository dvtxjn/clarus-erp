from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, func

from app.core.database import Base
from app.models.soft_delete import SoftDeleteMixin


class ShipmentContainer(SoftDeleteMixin, Base):
    """
    One container of a shipment, with its arrival at the FPOD (inland ICD: Panipat, Garhi, …) — where the
    free days start for inland shipments (client, 2026-09-30). Filled from ICEGATE's ICD BL status
    (MBL only) or typed in; a hand-edited arrival date (is_manual) is never overwritten by a refresh.
    """
    __tablename__ = "shipment_containers"

    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id"), nullable=False, index=True)
    container_no = Column(String, nullable=False)
    status = Column(String, nullable=True)            # FCL / LCL
    arrival_date = Column(Date, nullable=True)        # at the FPOD (ICD)
    arrival_status = Column(String, nullable=True)    # ICEGATE's code, e.g. "I"
    tracking_status = Column(String, nullable=True)   # typed, e.g. "On rail" / "Held at Mundra" (not arrived yet)
    free_days = Column(Integer, nullable=True)        # typed when this container gets other than the standard 14
    source = Column(String, nullable=False, default="manual")  # icegate | manual
    is_manual = Column(Boolean, nullable=False, default=False)  # arrival edited by hand: refresh leaves it
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
