from sqlalchemy import Boolean, Column, Integer, String
from app.core.database import Base


class TrackerColumn(Base):
    """
    Org-wide tracker column settings (per-user show/hide lives in the user's
    grid layout instead).

    - Custom columns (is_custom=True): created from the UI; values live in
      Shipment.custom_fields[key]. Deleting one removes its values too.
    - Built-in columns only get a row here once they're removed (is_removed)
      — the data stays on the shipment, so a removed column can be restored.
    """
    __tablename__ = "tracker_columns"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True, nullable=False)
    label = Column(String, nullable=False)
    data_type = Column(String, nullable=False, default="text")  # text | date | number | boolean
    is_custom = Column(Boolean, nullable=False, default=False)
    is_removed = Column(Boolean, nullable=False, default=False)
