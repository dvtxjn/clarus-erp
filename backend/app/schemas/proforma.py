from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ChargeCalculationBasis, ChargeCategory, ProformaStatus


class ChargeMasterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    sac_code: str
    gst_rate: Decimal
    calculation_basis: ChargeCalculationBasis
    category: ChargeCategory = ChargeCategory.SERVICE
    default_rate: Optional[Decimal] = None
    is_active: bool


class ChargeMasterUpdate(BaseModel):
    """Rates screen: change a charge's standard rate / details. Fields left out are unchanged;
    default_rate null = no standard rate."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    sac_code: Optional[str] = Field(default=None, pattern=r"^\d{6}$")
    gst_rate: Optional[Decimal] = Field(default=None, ge=0, le=28)
    calculation_basis: Optional[ChargeCalculationBasis] = None
    category: Optional[ChargeCategory] = None
    default_rate: Optional[Decimal] = Field(default=None, ge=0)
    is_active: Optional[bool] = None


class ChargeMasterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    code: str = Field(min_length=1, max_length=20, pattern=r"^[A-Z0-9_]+$")
    sac_code: str = Field(default="996713", pattern=r"^\d{6}$")
    gst_rate: Decimal = Field(default=Decimal("18"), ge=0, le=28)
    calculation_basis: ChargeCalculationBasis = ChargeCalculationBasis.FLAT
    category: ChargeCategory = ChargeCategory.SERVICE
    default_rate: Optional[Decimal] = Field(default=None, ge=0)


class PricingRuleLine(BaseModel):
    """amount = per_container x containers + per_kg x weight (kg) + flat."""
    code: str = Field(min_length=1, max_length=20)
    per_container: Optional[Decimal] = Field(default=None, ge=0)
    per_kg: Optional[Decimal] = Field(default=None, ge=0)
    flat: Optional[Decimal] = Field(default=None, ge=0)
    category: Optional[ChargeCategory] = None  # default: the charge's own section


class PricingRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    importer_name: str = Field(min_length=1, max_length=200)
    seller_name: Optional[str] = Field(default=None, max_length=200)
    bill_to_role: Literal["seller", "buyer"]
    lines: list[PricingRuleLine] = []
    is_active: bool = True


class PricingRuleOut(PricingRuleIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class LicenceRate(PricingRuleLine):
    """A licence rate row; seller / port narrow it (most specific match wins)."""
    seller: Optional[str] = Field(default=None, max_length=200)
    port: Optional[str] = Field(default=None, max_length=10)


class LicenceIn(BaseModel):
    number: str = Field(min_length=1, max_length=40)
    importer_name: Optional[str] = Field(default=None, max_length=200)  # licence belongs to the BE importer
    rates: list[LicenceRate] = []
    is_active: bool = True
    notes: Optional[str] = Field(default=None, max_length=300)


class LicenceOut(LicenceIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ProformaLineItemCreate(BaseModel):
    charge_master_id: int
    description: Optional[str] = None
    rate: Decimal
    # Omit to use the charge's basis: per-container charges -> the shipment's
    # container count; flat charges -> 1.
    quantity: Optional[Decimal] = None
    # Optional overrides: invoice section, and an actual GST figure (e.g. IGST on
    # duty, GST on a CFS invoice) instead of gst_rate x amount
    category: Optional[ChargeCategory] = None
    gst_amount: Optional[Decimal] = Field(default=None, ge=0)


class ProformaLineItemUpdate(BaseModel):
    """Edit a line in place (draft proformas). gst_amount: a number = actual GST;
    null = back to gst_rate x amount."""
    description: Optional[str] = Field(default=None, max_length=200)
    rate: Optional[Decimal] = Field(default=None, ge=0)
    quantity: Optional[Decimal] = Field(default=None, gt=0)
    gst_amount: Optional[Decimal] = Field(default=None, ge=0)
    category: Optional[ChargeCategory] = None


class ProformaLineItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    proforma_id: int
    charge_master_id: int
    description: Optional[str] = None
    rate: Decimal
    quantity: Decimal
    amount: Decimal
    sac_code: str
    gst_rate: Decimal
    gst_amount: Decimal
    total: Decimal
    category: ChargeCategory = ChargeCategory.SERVICE
    gst_is_actual: bool = False
    is_manual: bool = False


class ProformaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipment_id: int
    version_number: int
    name: Optional[str] = None
    bill_to: Optional[str] = None
    bill_to_role: Optional[str] = None
    bill_to_org_id: Optional[int] = None
    bill_rate: Optional[Decimal] = None
    bill_rate_manual: bool = False
    suppressed: Optional[list[str]] = None  # document-derived lines removed by hand (keys like "CFS", "DO:Liner Inv")
    status: ProformaStatus
    extracted_data: Optional[dict] = None
    generated_filename: Optional[str] = None
    created_at: datetime
    line_items: list[ProformaLineItemOut] = []
    grand_total: Decimal = Decimal("0")  # payable to Clarus: Billed by Clarus + Reimbursement (no GST Difference)
    match_total: Optional[Decimal] = None  # HSS: + Royalty + GST Difference; seller and buyer copies must agree
    party: Optional[str] = None  # HSS: whose copy, by first name ("Earthman" / "Mahrishi")
    revisions: int = 0  # sent copies kept in history (edited again after sending)


class ProformaSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    proforma_id: int
    bill_rate: Optional[Decimal] = None
    grand_total: Optional[Decimal] = None
    drive_file_id: Optional[str] = None
    created_at: datetime


class ProformaStatusUpdate(BaseModel):
    """Change status and/or rename (name/bill_to); fields left out are unchanged."""
    status: Optional[ProformaStatus] = None
    name: Optional[str] = Field(default=None, max_length=80)
    bill_to: Optional[str] = Field(default=None, max_length=200)
    bill_to_org_id: Optional[int] = None  # organization repository entry for the Bill To details
    bill_rate: Optional[Decimal] = Field(default=None, ge=0)  # HSS bill rate per kg -> GST Difference


class ProformaCreate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=80)
    # HSS shipments: which party this invoice is for
    bill_to_role: Optional[Literal["seller", "buyer"]] = None


class RestoreIn(BaseModel):
    """Put a document-derived line back: a key from `suppressed`, or a charge code
    (CD / SD / CFS / DO / EC) to add it from the documents."""
    key: str = Field(min_length=1, max_length=40)


class FillResult(BaseModel):
    proforma: ProformaOut
    added: list[str]
    updated: list[str] = []  # Customs / Stamp Duty lines refreshed (e.g. new challan interest)
    skipped: list[str]  # what couldn't be filled and why
