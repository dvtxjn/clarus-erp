from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.sql import func

from app.core.database import Base


class DutyChallan(Base):
    """
    One row of the daily duty challan list (ICEGATE pending-challan export:
    IEC, Location Code, Doc type, Doc no., Doc date, Challan no., Due Amount),
    or a figure entered by hand. Every upload is kept; a BE's current figure is
    its most recent row. Due Amount = duty + interest, so
    interest = Due Amount - the BE's total duty. Matched to shipments by BE no
    at read time, so a BE number added to a shipment later is picked up too.
    """
    __tablename__ = "duty_challans"

    id = Column(Integer, primary_key=True)
    be_no = Column(String, nullable=False, index=True)
    be_date = Column(String, nullable=True)
    location_code = Column(String, nullable=True)
    iec = Column(String, nullable=True)
    challan_no = Column(String, nullable=True)
    due_amount = Column(Numeric(14, 2), nullable=False)
    source = Column(String, nullable=False, default="upload", server_default="upload")  # upload | manual
    filename = Column(String, nullable=True)
    # local time (not the DB's UTC now) so "updated today" follows the office's day
    uploaded_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now, server_default=func.now())
    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # when the list was made: ICEGATE's own stamp inside the .xlsx (client, 2026-10-01: an upload of
    # yesterday's file must not count as today's), else the entry time. "Latest" and "today" go by this.
    listed_at = Column(DateTime(timezone=True), nullable=True, index=True, default=lambda: datetime.now(timezone.utc))

    @property
    def as_of(self) -> datetime:
        return self.listed_at or self.uploaded_at


IST = timezone(timedelta(hours=5, minutes=30))


def ist_day(dt: datetime) -> date:
    """The office's (India) date of a stored time; times without a zone are UTC."""
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(IST).date()


def today_ist() -> date:
    return datetime.now(IST).date()
