"""
Shipping line destination charges invoices (imports) -> totals + charge lines.

Every shipping line prints its own layout, so this is label-based with a list
of patterns per figure; add a pattern when a new line's invoice doesn't read.
Samples it's built from (reference: client uploads, 2026-09-28):

  Maersk (tax invoice, 2 per BL is normal — e.g. THC/haulage/doc fee + a
  separate "Additional Import Service"):
      Terminal Handling Service - Destination 10 CNT 15,750.00 INR 157,500.00 IN IGST 18% 28,350.00 157,500.00
      SAC/HSN 996711
      Total Base Amount INR 1,102,760.00
      I-GST Total taxes (see tax specification) INR 198,496.80
      Total Payable Amount INR 1,301,256.80
      Bill of Lading 274014260
  Cordelia (proforma):
      5 INR 23,180 115,900 1.0 115,900
      THC- TERMINAL HANDLING CHARGES - NSFT (SAC:996711)
      Taxable Amount 135,500 / SGST (%) 9% INR 12,195 / CGST (%) 9% INR 12,195 / Total Amount INR 159,890
      HBL # : CSX26JEDNSA021814

Returns the same amount keys as the CFS reader (cfs_before_tax / cfs_gst /
cfs_after_tax / cfs_sanity_ok) so tracker sync treats all invoices alike, plus
carrier, invoice_no, is_proforma and `charges` (one dict per charge line).
What counts as cost inclusion (destination charges): see _classify — freight / surcharges in a foreign currency
are out, known destination heads are in whatever the currency, unknown foreign-currency lines are out and flagged
(client, 2026-09-30). Any line can be ticked back on / off by hand on the Overview.
"""
from __future__ import annotations

import re
from typing import Any, Optional

AMOUNT = r"([\d,]+(?:\.\d+)?)"

# (text on the invoice, display name) — first match wins
CARRIERS = [
    ("GOODRICH MARITIME", "Goodrich Maritime"), ("SEASTAR GLOBAL", "Seastar (Parekh)"), ("NAVIO SHIPPING", "Navio Shipping"),
    ("MAERSK", "Maersk"), ("CORDELIA", "Cordelia"), ("HAPAG", "Hapag-Lloyd"),
    ("MEDITERRANEAN SHIPPING", "MSC"), ("MSC ", "MSC"), ("CMA CGM", "CMA CGM"), ("OCEAN NETWORK EXPRESS", "ONE"),
    ("COSCO", "COSCO"), ("OOCL", "OOCL"), ("EVERGREEN", "Evergreen"), ("YANG MING", "Yang Ming"),
    ("HMM", "HMM"), ("ZIM ", "ZIM"), ("WAN HAI", "Wan Hai"), ("PACIFIC INTERNATIONAL LINES", "PIL"),
    ("X-PRESS FEEDERS", "X-Press Feeders"), ("UNIFEEDER", "Unifeeder"), ("SAMUDERA", "Samudera"),
    ("GOLD STAR", "Gold Star"), ("EMIRATES SHIPPING", "Emirates Shipping"), ("TS LINES", "TS Lines"),
]

BEFORE_TAX = [
    r"Total\s+Base\s+Amount\s+(?:INR\s+)?" + AMOUNT,
    r"Total\s+Excluding\s+Tax\s*:?\s*(?:INR\s+)?" + AMOUNT,              # CMA CGM
    r"Taxable\s+Value\s*\(INR\)\s*:?\s*" + AMOUNT,                        # MSC
    r"^\s*NET\s+" + AMOUNT + r"\s*INR\s*$",                                # Hapag-Lloyd
    r"Taxable\s+Amount\s*:?\s*(?:INR\s+)?" + AMOUNT,
    r"Total\s+Taxable\s+(?:Value|Amount)\s*:?\s*(?:INR|Rs\.?|₹)?\s*" + AMOUNT,
    r"Total\s*Amount\s*Before\s*Tax\s*:?\s*" + AMOUNT,
    r"Sub\s*-?\s*total\s*:?\s*(?:INR\s+)?" + AMOUNT,
]
GST_TOTAL = [
    r"Total\s+taxes\b[^\n]*?INR\s+" + AMOUNT,
    r"Total\s+GST\s+TAX\s*:?\s*" + AMOUNT,                                   # CMA CGM
    r"Total\s+GST\s+Amount\s*\(INR\)\s*:?\s*" + AMOUNT,                     # MSC
    r"Total\s+(?:GST|Tax)\s*(?:Amount)?\s*:?\s*(?:INR|Rs\.?|₹)?\s*" + AMOUNT,
    r"Tax\s*Amount\s*:?\s*GST\s*:?\s*" + AMOUNT,
]
# one GST component per line, e.g. "SGST (%) 9% INR 12,195" — summed when there's no total-tax line
GST_PART = re.compile(r"^\s*(?:[SCIU]-?GST)\b[^\n]*?(?:INR|Rs\.?|₹)\s*" + AMOUNT + r"\s*$", re.IGNORECASE | re.MULTILINE)
AFTER_TAX = [
    r"Total\s+Payable\s+Amount\s+(?:INR\s+)?" + AMOUNT,
    r"Total\s+Including\s+Tax\s*:?\s*(?:INR\s+)?" + AMOUNT,               # CMA CGM
    r"Total\s+Invoice\s+Amount\s*(?:INR)?\s*:?\s*" + AMOUNT,                # MSC
    r"Total\s+Invoice\s+Value\s*\(in\s+figure\)\s*:?\s*" + AMOUNT,          # ONE
    r"^\s*GROSS\s+" + AMOUNT + r"\s*INR\s*$",                              # Hapag-Lloyd
    r"Total\s+Invoice\s+(?:Value|Amount)\s*:?\s*(?:INR|Rs\.?|₹)?\s*" + AMOUNT,
    r"Total\s+Amount\s+After\s+Tax\s*:?\s*" + AMOUNT,
    r"Grand\s+Total\s*:?\s*(?:INR|Rs\.?|₹)?\s*" + AMOUNT,
    r"Total\s+Amount\s*:?\s*(?:INR|Rs\.?|₹)\s*" + AMOUNT,
]
BL_NO = [
    r"Bill\s+of\s+Lading\s*(?:No\.?|Number|#)?\s*:?\s*([A-Z0-9]{6,20})\b",
    r"\bB/L-\s*NO\.?\s*:?\s*([A-Z0-9]{8,20})\b",                           # Hapag-Lloyd
    r"BL\s+Number[^\n]*\n\s*\S+\s+\S+\s+\S+\s+([A-Z0-9]{8,20})\b",          # Navio (values under the headings)
    r"\b(MEDU[A-Z0-9]{6,12})\b",                                             # MSC
    r"\bM?HBL\s*#\s*:?\s*([A-Z0-9]{6,20})\b",
    r"\bB/?L\s*(?:No\.?|Number|#)\s*:?\s*([A-Z0-9]{8,20})\b",
]
INVOICE_NO = [
    r"Invoice\s+(?:Number|No\.?)\s*:?\s*(?=[A-Z0-9/-]*\d)([A-Z0-9/-]{6,})",
    r"Client\s+no:\s*Invoice\s+no:[^\n]*\n\s*\S+\s+([A-Z0-9/-]{6,})",           # MSC (values under the headings)
    r"Invoice\s+No\s+Invoice\s+Date[^\n]*\n\s*([A-Z0-9/-]{6,})",               # Navio
    r"Invoice\s*#\s*Inv\s*Date[\s\S]{0,200}?\n\s*([A-Z0-9]{8,20})\s+\d{2}/\d{2}/\d{4}",  # Cordelia
]

# Maersk: "<desc> <qty> <UOM> <rate> <CUR> <extended> [IN IGST 18% <tax>] <taxable INR>", next line "SAC/HSN 996711"
MAERSK_LINE = re.compile(
    r"^(?P<desc>[A-Za-z][^\n]*?)\s+(?P<qty>\d+(?:\.\d+)?)\s+(?P<uom>[A-Z]{2,5})\s+(?P<rate>[\d,]+\.\d{2})\s+(?P<cur>[A-Z]{3})\s+"
    r"[\d,]+\.\d{2}(?:\s+IN\s+\S+\s+\d+(?:\.\d+)?%\s+(?P<gst>[\d,]+\.\d{2}))?\s+(?P<amount>[\d,]+\.\d{2})\s*$")
# Cordelia: "<qty> <CUR> <rate> <amount> <ex.rate> <amount INR>", next line "<desc> (SAC:996711)"
AMOUNT_FIRST_LINE = re.compile(
    r"^(?P<qty>\d+(?:\.\d+)?)\s+(?P<cur>[A-Z]{3})\s+(?P<rate>[\d,]+(?:\.\d+)?)\s+[\d,]+(?:\.\d+)?\s+[\d.]+\s+(?P<amount>[\d,]+(?:\.\d+)?)\s*$")
SAC_IN_DESC = re.compile(r"\(SAC\s*:?\s*(\d{6})\)")
# Cordelia sometimes prints the unit note first: "D40H / 2,000 PER CTR 1 INR 1,600 1,600 1.0 1,600"
AMOUNT_FIRST_ANYWHERE = re.compile(
    r"(?:^|\s)(?P<qty>\d+(?:\.\d+)?)\s+(?P<cur>INR|USD|EUR)\s+(?P<rate>[\d,]+(?:\.\d+)?)\s+[\d,]+(?:\.\d+)?\s+[\d.]+\s+"
    r"(?P<amount>[\d,]+(?:\.\d+)?)\s*$")
# CMA CGM: "40HC C Terminal Handling Charge (DTHC) at destination IH 6UNI 17,925.00INR 107,550.00 107,550.00"
CMA_LINE = re.compile(
    r"^(?:\S+\s+[A-Z]\s+)?(?P<desc>[A-Za-z].*?)\s+[A-Z]{2}\s+(?P<qty>\d+)(?P<uom>[A-Z]{3})\s+(?P<rate>[\d,]+\.\d{2})"
    r"(?P<cur>[A-Z]{3})\s+[\d,]+\.\d{2}\s+(?P<amount>[\d,]+\.\d{2})\s*$")
# Hapag-Lloyd: "THC DESTINATION 996711 15725.00 INR 1 CTR 15725.00 INR G2"
HAPAG_LINE = re.compile(
    r"^(?P<desc>[A-Za-z].*?)\s+(?P<sac>99\d{4})\s+(?P<rate>[\d,]+\.\d{2})\s+(?P<cur>[A-Z]{3})\s+(?P<qty>\d+)\s+\S+\s+"
    r"(?P<amount>[\d,]+\.\d{2})\s+[A-Z]{3}\s+\S+\s*$")
# any line: "<description> <SAC 99xxxx> … <taxable> <GST %> <GST> [<GST %> <GST>]" — the GST must be that % of the amount
SAC_ANY = re.compile(r"\b(99\d{4})\b")
CURRENCY = re.compile(r"\b(INR|USD|EUR|AED|GBP|SGD|CNY|JPY)\b")
MONEY = r"[\d,]+\.\d{2}"
# overlapping (lookahead), so an exchange-rate column ("9,440.00 1.00 9,440.00 9.0 849.60") doesn't hide the pair
GST_PAIR = re.compile(r"(?<![\d,.])(?=(?P<taxable>" + MONEY + r")\s+(?P<rate>\d{1,2}(?:\.\d+)?)\s*%?\s+(?P<gst>" + MONEY + r")"
                      r"(?:\s+(?P<rate2>\d{1,2}(?:\.\d+)?)\s*%?\s+(?P<gst2>" + MONEY + r"))?)")
# charge heads that are freight / origin, not destination charges
FREIGHT_HEAD = re.compile(
    r"FREIGHT|\bBAS\b|\bBAF\b|BUNKER|\bEBS\b|\bCAF\b|CURRENCY\s+ADJ|PEAK\s+SEASON|\bPSS\b|\bGRI\b|"
    r"LOW\s+SULPHUR|\bLSS\b|\bORIGIN\b|EXPORT|\bWAR\b|WAR\s*RISK|\bWRS\b|EMERGENCY|OCEAN|\bEU\s*ETS\b|EMISSION|"
    r"CARBON|GENERAL\s+RATE|RATE\s+RESTORATION|CONGESTION\s+SURCHARGE|CANAL|SUEZ|PANAMA|PIRACY|\bAMS\b|\bENS\b", re.IGNORECASE)
# charge heads that are destination charges for certain — counted whatever the currency (e.g. ISPS in USD)
DEST_HEAD = re.compile(
    r"DESTINATION|IMPORT|\bTHC\b|TERMINAL|HANDLING|DOCUMENT|DOC(?:UMENTATION)?\s*FEE|DELIVERY\s+ORDER|\bD/?O\b|ISPS|"
    r"SECURITY|CONTAINER\s+PROTECT|CLEAN|WASH|HAULAGE|INLAND|DETENTION|DEMURRAGE|STORAGE|SEAL|SURVEY|TOLL|ADMIN|"
    r"MAINTENANCE|MANDATORY\s+USER|EQUIPMENT|B/?L\s+FEE|HOUSE\s+B/?L|REPAIR|LIFT|MOVEMENT|IMBALANCE|SERVICE\s+CHARGE",
    re.IGNORECASE)
SAC_LINE = re.compile(r"^SAC(?:/HSN)?\s*:?\s*(\d{6})\s*$")


def _num(raw: Optional[str]) -> Optional[float]:
    try:
        return float(raw.replace(",", "")) if raw else None
    except ValueError:
        return None


def _first(patterns: list[str], text: str) -> Optional[str]:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(1).strip()
    return None


def _desc_before(line: str, stop: int) -> str:
    """Charge name: the words before the SAC, up to the first number or currency code."""
    words = []
    for w in re.sub(r"^\d{1,2}\s+(?=[A-Za-z])", "", line[:stop]).split():
        if w[0].isdigit() or CURRENCY.fullmatch(w):
            break
        words.append(w)
    return " ".join(words).strip(" -:")


def _generic_line(line: str, prev: str) -> Optional[dict[str, Any]]:
    """A charge line on most invoices (Emirates, Seastar, Goodrich, Navio, MSC, ONE, HMM …)."""
    sac = SAC_ANY.search(line)
    if not sac:
        return None
    pair = None
    for m in GST_PAIR.finditer(line, sac.end()):
        taxable, rate, gst = _num(m["taxable"]), float(m["rate"]), _num(m["gst"])
        if taxable and rate and gst is not None and abs(taxable * rate / 100 - gst) <= max(1.0, gst * 0.02):
            pair = (m, taxable, gst + ((_num(m["gst2"]) or 0) if m["gst2"] and m["rate2"] and float(m["rate2"]) == rate else 0))
            break
    if pair is None:
        return None
    desc = _desc_before(line, sac.start())
    if not desc:
        return None  # a SAC summary row, not a charge
    if (len(desc.split()) == 1 and prev and not re.search(r"\d", prev) and re.search(r"[A-Za-z]{3}", prev)
            and not CURRENCY.search(prev) and not HEADER_WORDS.search(prev)):
        desc = f"{prev.strip()} {desc}"  # the name wrapped onto the line above (Emirates)
    cur = CURRENCY.search(line)
    return {"description": desc, "sac": sac.group(1), "currency": cur.group(1) if cur else "INR",
            "quantity": None, "rate": None, "amount": pair[1], "gst": pair[2]}


def _charges(lines: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen_maersk = False
    for i, line in enumerate(lines):
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        m = MAERSK_LINE.match(line.strip())
        if m:
            seen_maersk = True
            sac = SAC_LINE.match(nxt)
            out.append({"description": m["desc"].strip(), "sac": sac.group(1) if sac else None,
                        "currency": m["cur"], "quantity": _num(m["qty"]), "rate": _num(m["rate"]),
                        "amount": _num(m["amount"]), "gst": _num(m["gst"]) if m["gst"] else 0.0})
    if seen_maersk:
        return _classify(out, strict=True)

    # Cordelia: amounts first, the charge name (ending "(SAC:…)") on the following line(s)
    for i, line in enumerate(lines):
        m = AMOUNT_FIRST_LINE.match(line.strip()) or AMOUNT_FIRST_ANYWHERE.search(line.strip())
        if not m:
            continue
        name = []
        for nxt in lines[i + 1:i + 4]:
            name.append(nxt.strip())
            if SAC_IN_DESC.search(nxt):
                break
        text = " ".join(name)
        sac = SAC_IN_DESC.search(text)
        if sac:
            desc = text[:sac.start()].strip(" -")
        else:  # Cordelia proforma: the name is on the line above, no SAC
            prev = lines[i - 1].strip() if i else ""
            if not prev or re.search(r"\d{2,}", prev):
                continue
            desc = prev
        out.append({"description": desc, "sac": sac.group(1) if sac else None,
                    "currency": m["cur"], "quantity": _num(m["qty"]), "rate": _num(m["rate"]),
                    "amount": _num(m["amount"]), "gst": None})
    if out:
        return _classify(out)

    for line in lines:  # CMA CGM
        m = CMA_LINE.match(line.strip())
        if m:
            out.append({"description": m["desc"].strip(), "sac": None, "currency": m["cur"], "quantity": _num(m["qty"]),
                        "rate": _num(m["rate"]), "amount": _num(m["amount"]), "gst": None})
    if out:
        return _classify(out)

    prev = ""
    for line in lines:
        text = line.strip()
        h = HAPAG_LINE.match(text)
        c = _generic_line(text, prev) if not h else None
        if h:
            c = {"description": h["desc"].strip(), "sac": h["sac"], "currency": h["cur"], "quantity": _num(h["qty"]),
                 "rate": _num(h["rate"]), "amount": _num(h["amount"]), "gst": None}
        if c:
            out.append(c)
        prev = text
    return _classify(out)


def _classify(out: list[dict[str, Any]], strict: bool = False) -> list[dict[str, Any]]:
    """Which charges are destination charges (-> cost inclusion). Client rule (2026-09-30, final):
      - freight / surcharges in a foreign currency (basic ocean freight, emergency bunker, war surcharge, …): out
      - a head that is a destination charge for certain (THC, documentation, DO, ISPS, haulage, …): in, any currency
      - anything else in INR: in; anything else in a foreign currency: out, flagged to check
      - a freight-named head billed in INR: Maersk (strict — its invoices can carry freight) out, others in
        (their import invoices only carry destination charges, e.g. Cordelia's BAF in INR); both flagged
    The admin ticks any line back on / off on the Overview (manual override)."""
    for c in out:
        desc = c["description"] or ""
        inr = c["currency"] == "INR"
        freight_head = bool(FREIGHT_HEAD.search(desc))
        dest_head = bool(DEST_HEAD.search(desc)) and not (freight_head and not inr)
        if dest_head and not freight_head:
            c["in_cost_inclusion"], c["review"] = True, False
        elif freight_head and not inr:
            c["in_cost_inclusion"], c["review"] = False, False
        elif freight_head:  # INR, named like freight
            c["in_cost_inclusion"], c["review"] = not strict, strict
        elif inr:
            c["in_cost_inclusion"], c["review"] = True, False
        else:  # foreign currency, not a known head
            c["in_cost_inclusion"], c["review"] = False, True
    return out


AMOUNTS_ON_LINE = re.compile(MONEY)
# column headings — never part of a charge name
HEADER_WORDS = re.compile(r"\b(?:AMOUNT|RATE|QTY|QUANTITY|DESCRIPTION|CODE|TAXABLE|HSN|SAC|CURR|TOTAL|UNITS?)\b", re.IGNORECASE)


def _totals_from_lines(text: str, after: Optional[float]) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Totals without labels: a line whose amounts read taxable + GST(s) = total (Seastar, Goodrich,
    HMM), or — when the total is known — taxable + the GSTs after it = that total (Navio, Emirates)."""
    best = None
    for line in text.splitlines():
        nums = [_num(x) for x in AMOUNTS_ON_LINE.findall(line)]
        nums = [n for n in nums if n is not None]
        for start in range(len(nums)):
            for end in range(start + 2, len(nums)):
                base, taxes, total = nums[start], nums[start + 1:end], nums[end]
                t = sum(taxes)
                if base > 0 and 0.03 <= t / base <= 0.30 and abs(base + t - total) < 1.0:
                    if best is None or total > best[2]:
                        best = (base, round(t, 2), total)
        if after is not None and nums:
            base = nums[0]
            rest = [n for n in nums[1:] if abs(n - base) >= 0.005]
            t = sum(rest)
            if base > 0 and rest and 0.03 <= t / base <= 0.30 and abs(base + t - after) < 1.0:
                if best is None or after >= best[2]:
                    best = (base, round(t, 2), after)
    return best if best else (None, None, None)


def scan_shipping_line_text(text: str) -> dict[str, Any]:
    upper = text.upper()
    before = _num(_first(BEFORE_TAX, text))
    gst = _num(_first(GST_TOTAL, text))
    if gst is None:
        parts = [_num(x) for x in GST_PART.findall(text)]
        gst = sum(p for p in parts if p is not None) if parts else None
    after = _num(_first(AFTER_TAX, text))
    if before is None or after is None:
        b, g, a = _totals_from_lines(text, after)
        if b is not None:
            before, after = before if before is not None else b, after if after is not None else a
            gst = gst if gst is not None else g
    if gst is None and before is not None and after is not None and after >= before:
        gst = round(after - before, 2)
    if before is None and gst is not None and after is not None:
        before = round(after - gst, 2)

    charges = _charges(text.splitlines())
    result: dict[str, Any] = {
        "carrier": next((name for key, name in CARRIERS if key in upper), None),
        "invoice_no": _first(INVOICE_NO, text),
        "is_proforma": "PROFORMA" in upper or "PRO FORMA" in upper
        or bool(re.search(r"\bDRAFT\s+(?:TAX\s+)?INVOICE\b", upper)),
        "bl_no": _first(BL_NO, text),
        "be_no": None,
        "cfs_before_tax": before,
        "cfs_gst": gst,
        "cfs_after_tax": after,
        "charges": charges,
    }
    result["cfs_sanity_ok"] = None
    if None not in (before, gst, after):
        result["cfs_sanity_ok"] = abs(before + gst - after) < 1.0
    if charges and before is not None:
        # charge lines should add up to the base amount; if not, don't offer them for cost inclusion
        result["charges_complete"] = abs(sum(c["amount"] or 0 for c in charges) - before) < 1.0
    return result
