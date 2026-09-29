from sqlalchemy import JSON, Column, DateTime, String
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.core.database import Base


class AppSetting(Base):
    """Admin switches, one row per key (e.g. "e_invoicing": true)."""
    __tablename__ = "app_settings"

    key = Column(String(80), primary_key=True)
    value = Column(JSON, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# every setting the app knows, with its default
DEFAULTS = {
    # E-invoicing (IRN) applies to Clarus: an issued invoice whose e-invoice is filed can't be altered
    "e_invoicing": False,
}


def get_setting(db: Session, key: str):
    row = db.get(AppSetting, key)
    return row.value if row is not None else DEFAULTS.get(key)


def all_settings(db: Session) -> dict:
    saved = {r.key: r.value for r in db.query(AppSetting).all()}
    return {k: saved.get(k, v) for k, v in DEFAULTS.items()}
