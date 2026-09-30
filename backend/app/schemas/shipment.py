from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ShipmentStatus


class ShipmentBase(BaseModel):
    job: str = ""  # upcoming shipments often have no job number yet
    mbl: str
    hbl: Optional[str] = None
    be_no: Optional[str] = None
    be_dt: Optional[date] = None

    be_description: Optional[str] = None
    eta: Optional[date] = None
    inw: Optional[str] = None
    license: Optional[str] = None
    client: Optional[str] = None
    consignee: Optional[str] = None
    pod: Optional[str] = None
    container_status: Optional[str] = None
    cfs: Optional[str] = None
    container: Optional[str] = None
    gross_wt: Optional[str] = None
    poc: Optional[str] = None
    cleared_date: Optional[date] = None
    igm: Optional[str] = None
    delivery_status: Optional[str] = None
    remark: Optional[str] = None
    mbl_date: Optional[date] = None
    hbl_date: Optional[date] = None
    gw: Optional[str] = None
    total_pkg: Optional[str] = None
    pkg_code: Optional[str] = None
    line_no: Optional[str] = None
    igm_date: Optional[date] = None
    voyage: Optional[str] = None
    cont: Optional[str] = None
    shipping_line: Optional[str] = None
    eta_is_deadline: bool = False

    duty_paid: bool = False
    cfs_inv_received: bool = False
    line_paid: bool = False
    ooc: bool = False
    do: bool = False
    cfs_paid_by_us: bool = False
    line_paid_by_us: bool = False
    line_cost_inclusion: Optional[Literal["include", "exclude"]] = None  # None = auto
    missing_from_sheet_at: Optional[datetime] = None
    cfs_billed_as: Literal["reimbursement", "taxable"] = "reimbursement"
    tds_deducted: bool = False
    tds_on_cfs: bool = False
    is_hss: Optional[bool] = None  # None = work it out from the consignee ("SELLER - BUYER")
    hss_seller: Optional[str] = None
    hss_buyer: Optional[str] = None
    drive_folder_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_-]{10,200}$")
    drive_folder_link: Optional[str] = None

    remarks: Optional[str] = None
    fta_info: Optional[str] = None
    is_stuck: bool = False

    port: Optional[str] = None
    hs_code_id: Optional[int] = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class ShipmentCreate(ShipmentBase):
    pass


class ShipmentUpdate(BaseModel):
    """All fields optional — partial updates (PATCH semantics).

    `base`: the values the user saw for the fields being changed (custom columns under
    base["custom_fields"][key]). If someone else changed one of those fields since, the
    PATCH changes nothing and answers 409 with the conflicts. Without `base` the old
    last-write-wins behaviour applies (scripts, older clients)."""
    model_config = ConfigDict(extra="forbid")

    base: Optional[dict[str, Any]] = None

    job: Optional[str] = None
    mbl: Optional[str] = None
    hbl: Optional[str] = None
    be_no: Optional[str] = None
    be_dt: Optional[date] = None
    be_description: Optional[str] = None
    eta: Optional[date] = None
    inw: Optional[str] = None
    license: Optional[str] = None
    client: Optional[str] = None
    consignee: Optional[str] = None
    pod: Optional[str] = None
    container_status: Optional[str] = None
    cfs: Optional[str] = None
    container: Optional[str] = None
    gross_wt: Optional[str] = None
    poc: Optional[str] = None
    cleared_date: Optional[date] = None
    igm: Optional[str] = None
    delivery_status: Optional[str] = None
    remark: Optional[str] = None
    mbl_date: Optional[date] = None
    hbl_date: Optional[date] = None
    gw: Optional[str] = None
    total_pkg: Optional[str] = None
    pkg_code: Optional[str] = None
    line_no: Optional[str] = None
    igm_date: Optional[date] = None
    voyage: Optional[str] = None
    cont: Optional[str] = None
    shipping_line: Optional[str] = None
    duty_paid: Optional[bool] = None
    cfs_inv_received: Optional[bool] = None
    line_paid: Optional[bool] = None
    ooc: Optional[bool] = None
    do: Optional[bool] = None
    cfs_paid_by_us: Optional[bool] = None
    line_paid_by_us: Optional[bool] = None
    line_cost_inclusion: Optional[Literal["include", "exclude"]] = None  # null = auto
    cfs_billed_as: Optional[Literal["reimbursement", "taxable"]] = None
    tds_deducted: Optional[bool] = None
    tds_on_cfs: Optional[bool] = None
    is_hss: Optional[bool] = None
    hss_seller: Optional[str] = None
    hss_buyer: Optional[str] = None
    under_examination: Optional[bool] = None  # normally read from the OOC copy; can be set by hand
    # BE figures are read from the Assessed/OOC copy; editable to correct a misread
    assessable_value: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    igst_amount: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    duty_amount: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    drive_folder_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_-]{10,200}$")
    drive_folder_link: Optional[str] = None
    eta_is_deadline: Optional[bool] = None
    remarks: Optional[str] = None
    fta_info: Optional[str] = None
    is_stuck: Optional[bool] = None
    status: Optional[ShipmentStatus] = None
    port: Optional[str] = None
    hs_code_id: Optional[int] = None
    # merged into the existing values: {column key: value}; null value clears it
    custom_fields: Optional[dict[str, Any]] = None


class ShipmentOut(ShipmentBase):
    icegate: Optional[dict[str, Any]] = None       # ICEGATE read-out (read only)
    line_from_bl: Optional[dict[str, Any]] = None  # {"line", "note"} from the MBL's format (computed)
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: ShipmentStatus
    is_billed: bool
    is_hss: bool = False
    billed_at: Optional[datetime] = None
    is_archived: bool
    days: str  # computed: today - INW + 1, or 'Pending'
    # Cleared = Cleared Date + all five checks; otherwise it stays with the ongoing shipments
    is_fully_cleared: bool = False
    missing_for_clearance: list[str] = []
    # read from uploaded documents
    assessable_value: Optional[Decimal] = None
    igst_amount: Optional[Decimal] = None
    duty_amount: Optional[Decimal] = None
    cfs_amount_before_tax: Optional[Decimal] = None
    cfs_gst_amount: Optional[Decimal] = None
    cfs_amount_total: Optional[Decimal] = None
    line_amount_before_tax: Optional[Decimal] = None
    line_gst_amount: Optional[Decimal] = None
    line_amount_total: Optional[Decimal] = None
    ooc_date: Optional[date] = None
    under_examination: Optional[bool] = None
    examination_at: Optional[str] = None
    # CFS payment when we pay the CFS: basic + GST - 2% TDS on basic
    cfs_tds_amount: Optional[Decimal] = None
    cfs_payment_after_tds: Optional[Decimal] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    version: int = 1  # bumped on every write (conflict protection)


class ClientRename(BaseModel):
    old_name: str
    new_name: str = Field(min_length=1)


class ValueRename(ClientRename):
    field: Literal["client", "consignee"]


class ClientRenameOut(BaseModel):
    updated: int
