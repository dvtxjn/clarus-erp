from functools import lru_cache

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


def _defaults() -> dict:
    from app.invoice.company import BANK, NOTES, TERMS, company_settings_default

    return {
        # E-invoicing (IRN) applies to Clarus: an issued invoice whose e-invoice is filed can't be altered
        "e_invoicing": False,
        # printed on every invoice (Settings page)
        "company": company_settings_default(),
        "bank": [list(x) for x in BANK],
        "final_terms": list(TERMS),
        "proforma_notes": list(NOTES),
    }


@lru_cache(maxsize=1)
def defaults() -> dict:
    """Every setting the app knows, with its default (built on first use: the invoice module
    that holds some defaults imports this one)."""
    return _defaults()


def get_setting(db: Session, key: str):
    row = db.get(AppSetting, key)
    return row.value if row is not None else defaults().get(key)


def all_settings(db: Session) -> dict:
    saved = {r.key: r.value for r in db.query(AppSetting).all()}
    return {k: saved.get(k, v) for k, v in defaults().items()}
