from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.core.database import Base


class OrganizationEntry(Base):
    """
    Spec §5.1 "Organization Repository": the parties we bill, with their
    details for the invoice's Bill To block. AD Code -> officially registered
    importer name is also used to flag a mismatch between the name printed on
    a BE and the registered name. Added from the dashboard, or bulk-imported
    from the filing software's 'Organization List' export.

    short_names: comma-separated names the tracker uses for this party, e.g.
    "Mahrishi" or "HKR" (the part of an HSS consignee after/before the '-'),
    so the invoice can find its details.
    """
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    # not unique: group companies can share one (Earthman / Earthstar 0511029)
    ad_code = Column(String(7), index=True, nullable=True)
    name = Column(String, nullable=False)
    short_names = Column(String, nullable=True)
    gstin = Column(String, nullable=True)
    pan = Column(String, nullable=True)
    iec = Column(String, nullable=True)
    address = Column(String, nullable=True)
    state = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    # False: on shipments involving this party, shipping line invoices are not added to the
    # proforma's cost inclusion unless switched on for that shipment (client: Harekrishna Rubber)
    line_in_cost_inclusion = Column(Boolean, default=True, nullable=False, server_default="1")
    updated_at = Column(DateTime(timezone=True), nullable=True, default=datetime.now, onupdate=datetime.now)
