from sqlalchemy import Column, Integer, String, Numeric, Boolean, Enum as SAEnum
from app.core.database import Base
from app.core.enums import ChargeCalculationBasis, ChargeCategory


class ChargeMasterEntry(Base):
    """
    Spec §5.4 (as corrected in §5.3/§5.6): a user-manageable library of
    chargeable line items, NOT a fixed hardcoded set. New charges can be
    added here and become immediately selectable on any proforma — no
    template/cell-layout change needed, unlike the reference tool.

    Seeded from the client's actual billing export (Charges CSV) plus the
    confirmed SAC scope (996711/712/713/719) — see seed data /
    reference/Charges_27Sep2026_1215AM.csv for the source list.
    """
    __tablename__ = "charge_master_entries"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    code = Column(String, unique=True, nullable=False)  # e.g. "AC", "CFS", "CD" — from client's export

    sac_code = Column(String, nullable=False)  # constrained to 996711/712/713/719 per spec §5.4, not hard-locked
    gst_rate = Column(Numeric(5, 2), nullable=False, default=18.00)

    calculation_basis = Column(SAEnum(ChargeCalculationBasis), nullable=False, default=ChargeCalculationBasis.FLAT)
    category = Column(SAEnum(ChargeCategory), nullable=False, default=ChargeCategory.SERVICE,
                      server_default=ChargeCategory.SERVICE.name)
    default_rate = Column(Numeric(12, 2), nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
