"""
One-time seed data, sourced directly from the spec's confirmed decisions.
Run with: python -m app.seed

Seeds:
  1. The tyre HS code + its base required-document list (spec §3.1)
  2. The full charge master from the client's actual billing export,
     with SAC codes applied per spec §5.4's final resolved table
     (996711 for container-handling charges, 996713 for everything else —
     the "safe default" from §6 item #4: ALL of Terminal/Yard/Empty Lift
     On/Off default to 996711 since they're all handling-type charges)
  3. One admin user (change the password immediately after first login)
"""
from decimal import Decimal

from app.core.database import SessionLocal
from app.core.migrate import run_migrations
from app.core.enums import DocumentType, ChargeCalculationBasis, ChargeCategory, UserRole
from app.core.security import hash_password
from app.models.document import HSCode, RequiredDocument
from app.models.charge import ChargeMasterEntry
from app.models.user import User
from app.models.port import Port

# spec §3.1 — base document set (same for all HS codes so far; tyre-specific
# addition is the merged FORM_6_9)
BASE_DOCUMENT_TYPES = [
    DocumentType.CFS_PROFORMA_INVOICE,
    DocumentType.CFS_TAX_INVOICE,
    DocumentType.ASSESSED_BILL_OF_ENTRY,
    DocumentType.OOC_BILL_OF_ENTRY,
    DocumentType.GATEPASS_BILL_OF_ENTRY,
    DocumentType.BL_COPY,
    DocumentType.HBL_COPY,
    DocumentType.PACKING_LIST,
    DocumentType.INSURANCE,
    DocumentType.SHIPPING_LINE_PROFORMA,  # optional
    DocumentType.SHIPPING_LINE_INVOICE,  # destination charges — the proforma's shipping line "cost inclusion"
    DocumentType.SHIPPING_LINE_RECEIPT,  # optional
    DocumentType.CFS_RECEIPT,  # optional
    DocumentType.DO_LETTER,
    DocumentType.EMPTY_LETTER,  # optional — see OPTIONAL_DOCS
    DocumentType.HSS_AGREEMENT,
    DocumentType.STAMP_DUTY,
    DocumentType.CERTIFICATE_OF_ORIGIN,
    DocumentType.FTA_CERTIFICATE_OF_ORIGIN,
]

# Port/ICD codes seen in the live tracker (names to confirm with client)
PORTS = [
    ("INMUN1", "Mundra"),
    ("INNSA1", "Nhava Sheva"),
    ("INDWN6", "Panipat"),
    ("INGHR6", "Garhi"),
]

TYRE_HS_CODE = "40040000"  # confirmed with client
TYRE_EXTRA_DOCS = [DocumentType.FORM_6_9]  # Form 6 & 9 arrive as one merged file
# Listed on the checklist but not flagged when missing (Empty letter is
# often part of the DO letter)
OPTIONAL_DOCS = {
    DocumentType.EMPTY_LETTER,
    DocumentType.INSURANCE,
    DocumentType.HBL_COPY,
    DocumentType.HSS_AGREEMENT,  # HSS shipments only; Stamp Duty is paid on the HSS agreement
    DocumentType.STAMP_DUTY,
    DocumentType.FTA_CERTIFICATE_OF_ORIGIN,
    DocumentType.CFS_PROFORMA_INVOICE,  # CFS isn't paid by us for every client
    DocumentType.CFS_TAX_INVOICE,
    DocumentType.CFS_RECEIPT,
    DocumentType.SHIPPING_LINE_PROFORMA,
    DocumentType.SHIPPING_LINE_RECEIPT,
}

# spec §5.4 — SAC 996711 for container-handling-type charges, 996713 for
# everything else (reimbursement-under-Agency model)
CONTAINER_HANDLING_CODES = {"TC", "YARD", "LOLO"}
# Client-confirmed: Agency and Examination are billed per container ((rate x containers) + GST)
PER_CONTAINER_CODES = {"AC", "EC"}
# Rates from the client's invoice template (per container); editable per proforma
DEFAULT_RATES = {"AC": Decimal("7000"), "EC": Decimal("18000"), "ROY": Decimal("0.75"),
                 "SBOND": Decimal("1500"), "DC": Decimal("1500")}  # editable on the Rates screen
# Royalty is per kg of the BE gross weight (HSS only); GST Difference is worked out, no GST of its own
PER_KG_CODES = {"ROY"}
NO_GST_CODES = {"GSTD"}
# Invoice sections, following the template: our fees vs reimbursements at actuals vs
# the shipping line "cost inclusion". Default mapping — client to confirm with bills.
ROYALTY_CODES = {"ROY"}
REIMBURSEMENT_CODES = {"GSTD", "CD", "CDB", "SD", "CFS", "INS", "BONDC", "DELIVERYCHARGE", "TC", "YARD", "LOLO"}
COST_INCLUSION_CODES = {"DO"}
SAC_CONTAINER_HANDLING = "996711"
SAC_AGENCY = "996713"

# (name, code) — from Charges_27Sep2026_1215AM.csv
CHARGES = [
    ("Agency Charges", "AC"),
    ("Bond Charges", "SBOND"),
    ("Bond Charges (Reimbursement)", "BONDC"),
    ("CFS Charges", "CFS"),
    ("Customs Duty", "CD"),
    ("Customs Duty Balance", "CDB"),
    ("Delivery Charges", "DELIVERYCHARGE"),
    ("Documentation Charges", "DC"),
    ("Empty Lift On/Off", "LOLO"),
    ("Examination Charges", "EC"),
    ("Insurance Charges", "INS"),
    ("Other Charges", "OTHERCHARGES"),
    ("Registration Charges", "RC"),
    ("Shipping Line Charges", "DO"),
    ("Stamp Duty", "SD"),
    ("Terminal Charges", "TC"),
    ("Yard Charges", "YARD"),
    ("Royalty", "ROY"),
    ("GST Difference", "GSTD"),
]


def seed():
    run_migrations()
    db = SessionLocal()
    try:
        # --- HS code + required documents ---
        if not db.query(HSCode).filter(HSCode.code == TYRE_HS_CODE).first():
            hs = HSCode(code=TYRE_HS_CODE, description="Tyres")
            db.add(hs)
            db.flush()
            for doc_type in BASE_DOCUMENT_TYPES + TYRE_EXTRA_DOCS:
                db.add(RequiredDocument(hs_code_id=hs.id, document_type=doc_type, optional=doc_type in OPTIONAL_DOCS))
            print(f"Seeded HS code {TYRE_HS_CODE} with {len(BASE_DOCUMENT_TYPES) + len(TYRE_EXTRA_DOCS)} required docs")

        # --- Ports ---
        for code, name in PORTS:
            if not db.query(Port).filter(Port.code == code).first():
                db.add(Port(code=code, name=name))

        # --- Charge master ---
        for name, code in CHARGES:
            if db.query(ChargeMasterEntry).filter(ChargeMasterEntry.code == code).first():
                continue
            sac = SAC_CONTAINER_HANDLING if code in CONTAINER_HANDLING_CODES else SAC_AGENCY
            db.add(ChargeMasterEntry(
                name=name,
                code=code,
                sac_code=sac,
                gst_rate=Decimal("0.00") if code in NO_GST_CODES else Decimal("18.00"),
                calculation_basis=(ChargeCalculationBasis.PER_CONTAINER if code in PER_CONTAINER_CODES
                                   else ChargeCalculationBasis.PER_KG if code in PER_KG_CODES
                                   else ChargeCalculationBasis.FLAT),
                category=(ChargeCategory.ROYALTY if code in ROYALTY_CODES
                          else ChargeCategory.COST_INCLUSION if code in COST_INCLUSION_CODES
                          else ChargeCategory.REIMBURSEMENT if code in REIMBURSEMENT_CODES
                          else ChargeCategory.SERVICE),
                default_rate=DEFAULT_RATES.get(code),
                is_active=True,
            ))
        print(f"Seeded {len(CHARGES)} charge master entries")

        # --- Admin user ---
        if not db.query(User).filter(User.role == UserRole.ADMIN).first():
            admin = User(
                email="admin@example.com",
                hashed_password=hash_password("changeme"),
                full_name="Admin",
                role=UserRole.ADMIN,
                can_access_billing=True,
            )
            db.add(admin)
            print("Seeded admin user: admin@example.com / changeme — CHANGE THIS PASSWORD IMMEDIATELY")

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
