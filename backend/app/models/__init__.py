"""
Import every model here so Base.metadata sees all tables — required for
`Base.metadata.create_all()` (dev) and for Alembic autogenerate to find them.
"""
from app.models.user import User, UserPortAccess  # noqa: F401
from app.models.shipment import Shipment  # noqa: F401
from app.models.document import HSCode, RequiredDocument, ShipmentDocument  # noqa: F401
from app.models.charge import ChargeMasterEntry  # noqa: F401
from app.models.proforma import Proforma, ProformaLineItem  # noqa: F401
from app.models.audit import AuditLogEntry  # noqa: F401
from app.models.organization import OrganizationEntry  # noqa: F401
from app.models.challan import DutyChallan  # noqa: F401
from app.models.pricing_rule import PricingRule  # noqa: F401
from app.models.licence import Licence  # noqa: F401
from app.models.final_invoice import FinalInvoice, InvoiceCounter  # noqa: F401
from app.models.port import Port  # noqa: F401
from app.models.tracker_column import TrackerColumn  # noqa: F401
from app.models.storage import DriveFolder, StoredFile  # noqa: F401
from app.models.backup import BackupRun  # noqa: F401
from app.models.settings import AppSetting  # noqa: F401
from app.models.payment import Payment, PaymentAllocation  # noqa: F401
from app.models.container import ShipmentContainer  # noqa: F401
