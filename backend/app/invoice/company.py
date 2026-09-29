"""Issuer details printed on every invoice (from the client's template
reference/Clarus_Logistics_Proforma_Invoice_flexible.xlsm)."""

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
