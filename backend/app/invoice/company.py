"""Issuer details printed on every invoice (from the client's template
reference/Clarus_Logistics_Proforma_Invoice_flexible.xlsm).

The constants below are the defaults; the admin edits them on the Settings page (client,
2026-09-30), and invoices read the live values through company() / bank() / terms() / notes()."""

COMPANY = {
    "name": "CLARUS LOGISTICS LLP",
    "address": "5th Floor, 507, Raheja Arcade, Sector 11, Plot No 61, CBD Belapur, Navi Mumbai, Thane, Maharashtra - 400614",
    "tax_line": "GSTIN: 27AAVFC6734E1Z4      PAN: AAVFC6734E      State: Maharashtra [27]",
    "contact_line": "Email: business@claruslogistics.in      Phone: +91 98106 19155",
    # as printed on the final invoices
    "gstin": "27AAVFC6734E1Z4", "pan": "AAVFC6734E", "cin": "ACR-5764", "state_code": "27", "state": "MAHARASHTRA",
    "address_lines": ["5th Floor, 507, Raheja Arcade, Sector - 11, Plot No - 61, CBD Belapur, Navi Mumbai,",
                      "Thane, Maharashtra, 400614"],
}

# final invoices (tax / reimbursement)
TERMS = [
    "In case of any discrepancy in the invoice, please bring the same to our attention within 7 days of receipt of "
    "invoice; else the same would be treated as correct.",
    "Delay in payment beyond the agreed credit period will attract interest @ 18% p.a.",
    "Government Taxes applied as per the prevailing rates.",
    "All disputes are subject to NAVI MUMBAI Jurisdiction.",
]

BANK = [
    ("Account Name", "CLARUS LOGISTICS LLP"),
    ("Bank Name", "HDFC Bank"),
    ("Account No.", "50200115672930"),
    ("IFSC Code", "HDFC0004560"),
    ("Account Type", "Current Account"),
]

NOTES = [
    "INCASE OF HSS - HSS SELLER PAYS BUYER AND BUYER PAYS CLARUS LOGISTICS",
    "This is a Proforma Invoice for reference purposes and is subject to revision based on actual charges "
    "levied by customs/port/shipping line authorities.",
]

# Clarus brand palette (logo orange + warm neutrals), kept low-key
BRAND = "D26B21"      # company name, grand total
BAR = "3A2F29"        # section bars (warm charcoal)
HEADER = "F3E4D7"     # column header cells
SUBTOTAL = "FAF2EB"   # subtotal rows
HIGHLIGHT = "FBE7D3"  # the HSS note


# --- live values (Settings page), falling back to the defaults above ---

def _setting(key: str):
    from app.core.database import SessionLocal
    from app.models.settings import get_setting

    try:
        with SessionLocal() as db:
            return get_setting(db, key)
    except Exception:  # noqa: BLE001 — no database (e.g. a PDF rendered offline): defaults
        return None


def company_settings_default() -> dict:
    """The editable company fields (Settings → Company)."""
    return {"name": COMPANY["name"], "address_lines": list(COMPANY["address_lines"]), "gstin": COMPANY["gstin"],
            "pan": COMPANY["pan"], "cin": COMPANY["cin"], "state_code": COMPANY["state_code"], "state": COMPANY["state"],
            "email": "business@claruslogistics.in", "phone": "+91 98106 19155"}


def company() -> dict:
    c = {**company_settings_default(), **(_setting("company") or {})}
    lines = [x for x in c.get("address_lines") or [] if x]
    state = (c.get("state") or "").title()
    return {
        **c,
        "address": " ".join(lines),
        "address_lines": lines,
        "tax_line": f"GSTIN: {c['gstin']}      PAN: {c['pan']}      State: {state} [{c['state_code']}]",
        "contact_line": f"Email: {c['email']}      Phone: {c['phone']}",
    }


def bank() -> list[tuple[str, str]]:
    saved = _setting("bank")
    return [tuple(x) for x in saved] if saved else BANK


def terms() -> list[str]:
    return _setting("final_terms") or TERMS


def notes() -> list[str]:
    return _setting("proforma_notes") or NOTES
