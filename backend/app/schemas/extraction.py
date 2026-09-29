from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class CFSScan(BaseModel):
    filename: str
    error: Optional[str] = None
    be_no: Optional[str] = None
    bl_no: Optional[str] = None
    cfs_before_tax: Optional[float] = None
    cfs_gst: Optional[float] = None
    cfs_after_tax: Optional[float] = None
    cfs_sanity_ok: Optional[bool] = None
    matched_row: Optional[int] = None  # index into BatchScanOut.rows
    matched_by: Optional[str] = None   # "BE Number" / "BL Number"


class BERow(BaseModel):
    """One Bill of Entry = one row of the (future) batch fee-entry screen."""
    filename: str
    error: Optional[str] = None
    missing: List[str] = []
    port_code: Optional[str] = None
    be_no: Optional[str] = None
    be_date: Optional[str] = None  # DD.MM.YYYY, as the reference tool emits
    importer_name: Optional[str] = None
    ad_code: Optional[str] = None
    mawb: Optional[str] = None
    hawb: Optional[str] = None
    cont_count: Optional[str] = None
    gross_wt: Optional[str] = None
    tot_ass_val: Optional[str] = None
    igst: Optional[str] = None
    tot_amount: Optional[str] = None
    # AD-code registry check (spec §5.1): YES = BE name differs from registered name
    name_mismatch: str = "N/A"
    billing_name: Optional[str] = None
    # duplicate detection (spec §5.3)
    duplicate_in_batch: bool = False
    existing_shipment_id: Optional[int] = None  # a shipment already has this BE number
    cfs: Optional[CFSScan] = None


class BatchScanOut(BaseModel):
    rows: List[BERow]
    unmatched_cfs: List[CFSScan]


class ChallanOut(BaseModel):
    due_amounts: dict
    note: Optional[str] = None


class OrganizationBase(BaseModel):
    ad_code: Optional[str] = Field(default=None, pattern=r"^\d{7}$")
    name: str = Field(min_length=1)
    # names the tracker uses for this party, comma-separated (e.g. "Mahrishi")
    short_names: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    iec: Optional[str] = None
    address: Optional[str] = None
    state: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool = True
    line_in_cost_inclusion: bool = True  # False: shipping line not in cost inclusion by default


class OrganizationOut(OrganizationBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    updated_at: Optional[datetime] = None


class OrgImportOut(BaseModel):
    created: int
    updated: int
