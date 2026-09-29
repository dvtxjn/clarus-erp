"""
Sandbox (client, 2026-09-30, P4): a separate copy of the app, with its own database, for staff
to try things on made-up data. SANDBOX=1 on that deployment:
  - a "Sandbox — sample data" banner and the demo login on the login page;
  - no admin login and no rates / licences / pricing rules (invoicing is kept private);
  - reset() loads the one small showcase data set (run once when the sandbox is set up; again
    only if someone wants it back to the start).
reset() refuses to run unless SANDBOX=1 AND the database name contains "sandbox" — so it can
never touch the real data.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

from sqlalchemy import text

from app.core.database import DATABASE_URL, SessionLocal, engine

DEMO_EMAIL = "demo@sandbox.claruslogistics.in"
DEMO_PASSWORD = "try-clarus-erp"  # public on purpose: shown on the sandbox login page
DEMO_NAME = "Sandbox Demo"


def is_sandbox() -> bool:
    return os.getenv("SANDBOX", "0") == "1"


def _safe_to_wipe() -> bool:
    return is_sandbox() and "sandbox" in DATABASE_URL.rsplit("/", 1)[-1].lower()


# made-up clients (not the real ones)
ORGS = [
    ("SUNRISE POLYMERS PVT LTD", "27AAACS1111A1Z1", "Plot 12, MIDC Taloja, Navi Mumbai", "Maharashtra"),
    ("BLUEWAVE RUBBER INDUSTRIES", "24AABCB2222B1Z2", "Survey 88, GIDC Vapi, Valsad", "Gujarat"),
    ("EVEREST TRADERS", "27AAECE3333C1Z3", "Office 4, Vashi, Navi Mumbai", "Maharashtra"),
    ("METRO RECYCLERS", "07AAFCM4444D1Z4", "Narela Industrial Area, Delhi", "Delhi"),
]


def _shipments(today: date) -> list[dict]:
    d = lambda n: today + timedelta(days=n)  # noqa: E731
    inw = lambda n: (today + timedelta(days=n)).strftime("%d-%b-%Y")  # noqa: E731
    base = [
        # client, consignee, port, eta offset, containers, weight, stage flags …
        dict(job="S101", client="SUNRISE", consignee="SUNRISE POLYMERS PVT LTD", port="INNSA1", eta=d(9),
             container="2", gross_wt="42.500 MTS", mbl="SMPLNSA0001001", cfs="Speedy CFS", shipping_line="Oceanic Lines",
             remarks="Awaiting BL copy", eta_is_deadline=True),
        dict(job="S102", client="SUNRISE", consignee="SUNRISE POLYMERS PVT LTD", port="INNSA1", eta=d(4),
             container="1", gross_wt="21.300 MTS", mbl="SMPLNSA0001002", igm="7000101", cfs="Speedy CFS",
             shipping_line="Oceanic Lines", eta_is_deadline=True),
        dict(job="S103", client="SUNRISE", consignee="SUNRISE POLYMERS PVT LTD", port="INNSA1", eta=d(-3), inw=inw(-3),
             container="3", gross_wt="63.900 MTS", mbl="SMPLNSA0001003", igm="7000102", be_no="9000101", be_dt=d(-2),
             cfs="Harbour CFS", shipping_line="Blue Anchor", container_status="Arrived"),
        dict(job="S104", client="SUNRISE", consignee="SUNRISE POLYMERS PVT LTD", port="INNSA1", eta=d(-8), inw=inw(-8),
             container="1", gross_wt="20.100 MTS", mbl="SMPLNSA0001004", igm="7000103", be_no="9000102", be_dt=d(-6),
             duty_paid=True, cfs="Harbour CFS", shipping_line="Blue Anchor", remark="EXAM", under_examination=True),
        dict(job="S201", client="BLUEWAVE", consignee="BLUEWAVE RUBBER INDUSTRIES", port="INMUN1", eta=d(12),
             container="5", gross_wt="104.200 MTS", mbl="SMPLMUN0002001", hbl="SMPLH2001", cfs="Portside Logistics",
             shipping_line="Seaway Express"),
        dict(job="S202", client="BLUEWAVE", consignee="BLUEWAVE RUBBER INDUSTRIES", port="INMUN1", eta=d(-5), inw=inw(-5),
             container="4", gross_wt="88.000 MTS", mbl="SMPLMUN0002002", igm="7000201", be_no="9000201", be_dt=d(-4),
             duty_paid=True, ooc=True, ooc_date=d(-1), cfs="Portside Logistics", shipping_line="Seaway Express",
             container_status="OUT", delivery_status="In transit"),
        dict(job="S203", client="BLUEWAVE", consignee="BLUEWAVE RUBBER INDUSTRIES", port="INMUN1", eta=d(-15), inw=inw(-15),
             container="2", gross_wt="41.750 MTS", mbl="SMPLMUN0002003", igm="7000202", be_no="9000202", be_dt=d(-13),
             duty_paid=True, ooc=True, ooc_date=d(-10), cfs_inv_received=True, line_paid=True, do=True,
             cleared_date=d(-9), cfs="Portside Logistics", shipping_line="Seaway Express", container_status="OUT",
             delivery_status="Delivered"),
        # HSS: "SELLER - BUYER" in the consignee
        dict(job="S301", client="EVEREST", consignee="EVEREST TRADERS - METRO RECYCLERS", port="INNSA1", eta=d(6),
             container="5", gross_wt="110.600 MTS", mbl="SMPLNSA0003001", cfs="Harbour CFS", shipping_line="Blue Anchor",
             remarks="HSS — agreement pending", eta_is_deadline=True),
        dict(job="S302", client="EVEREST", consignee="EVEREST TRADERS - METRO RECYCLERS", port="INNSA1", eta=d(-6), inw=inw(-6),
             container="3", gross_wt="66.300 MTS", mbl="SMPLNSA0003002", igm="7000301", be_no="9000301", be_dt=d(-5),
             cfs="Harbour CFS", shipping_line="Blue Anchor", remark="SUP"),
        # Delhi / ICD
        dict(job="S401", client="METRO", consignee="METRO RECYCLERS", port="INDWN6", eta=d(-2), inw=inw(-2),
             container="2", gross_wt="44.000 MTS", mbl="SMPLDWN0004001", igm="7000401", cfs="Northern ICD",
             shipping_line="Oceanic Lines", remarks="Rail to ICD"),
        dict(job="S402", client="METRO", consignee="METRO RECYCLERS", port="INGHR6", eta=d(15), container="1",
             gross_wt="19.900 MTS", mbl="SMPLGHR0004002", shipping_line="Seaway Express"),
        dict(job="S403", client="METRO", consignee="METRO RECYCLERS", port="INDWN6", eta=d(-20), inw=inw(-20),
             container="3", gross_wt="61.200 MTS", mbl="SMPLDWN0004003", igm="7000402", be_no="9000401", be_dt=d(-18),
             duty_paid=True, ooc=True, ooc_date=d(-14), cfs_inv_received=True, line_paid=True, do=True,
             cleared_date=d(-12), cfs="Northern ICD", shipping_line="Oceanic Lines", container_status="OUT",
             delivery_status="Delivered"),
    ]
    return base


def reset(today: date | None = None) -> dict:
    """Wipe the sandbox and load the sample set. Refuses anywhere but a sandbox database."""
    if not _safe_to_wipe():
        raise RuntimeError("Not a sandbox (needs SANDBOX=1 and a database named *sandbox*) — refusing to wipe.")
    from app import models  # noqa: F401
    from app.core.enums import UserRole
    from app.core.security import hash_password
    from app.core.status_rules import proven_status
    from app.models.organization import OrganizationEntry
    from app.models.shipment import Shipment
    from app.models.user import User

    today = today or date.today()
    with engine.begin() as c:  # TRUNCATE skips the "never delete" row triggers — sandbox only
        c.execute(text(
            "TRUNCATE payment_allocations, payments, final_invoices, proforma_line_items, proformas, "
            "shipment_documents, audit_log_entries, organizations, licences, pricing_rules, shipments "
            "RESTART IDENTITY CASCADE"))
        c.execute(text("UPDATE charge_master_entries SET default_rate = NULL"))  # rates stay private
    with SessionLocal() as db:
        for u in db.query(User).all():  # nobody but the demo user; never an admin
            u.is_active = u.email == DEMO_EMAIL
        demo = db.query(User).filter(User.email == DEMO_EMAIL).first()
        if demo is None:
            demo = User(email=DEMO_EMAIL, full_name=DEMO_NAME, role=UserRole.IMPORT_MANAGER, is_active=True,
                        can_access_billing=False, hashed_password=hash_password(DEMO_PASSWORD))
            db.add(demo)
        demo.role, demo.can_access_billing = UserRole.IMPORT_MANAGER, False
        demo.hashed_password = hash_password(DEMO_PASSWORD)
        for name, gstin, address, state in ORGS:
            db.add(OrganizationEntry(name=name, gstin=gstin, pan=gstin[2:12], address=address, state=state))
        for row in _shipments(today):
            s = Shipment(**row)
            db.add(s)
            db.flush()
            s.status = proven_status(s)
        db.commit()
        return {"shipments": len(_shipments(today)), "organizations": len(ORGS)}
