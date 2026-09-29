"""PDF of a final invoice (tax / reimbursement): the content of the client's current
invoices (CL/200/26-27, RI/CL/200/26-27) in the Clarus look; one A4 page, no split words."""
from __future__ import annotations

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.platypus import KeepInFrame, SimpleDocTemplate, Spacer, Table

from app.invoice.pdf import (
    BAR_C, BRAND_C, GRID, HEAD_C, HEIGHT, MARGIN, MUTED, SUB_C, WIDTH, ClarusLogo, _p, _style, num,
)


def _date(iso):
    return date.fromisoformat(iso).strftime("%d-%b-%Y") if iso else "-"


def render_final_pdf(inv: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN,
                            bottomMargin=MARGIN, title=f"{inv['title']} {inv['number'] or 'DRAFT'}")
    co, cu, h, t = inv["company"], inv["customer"], inv["header"], inv["totals"]
    body: list = []

    # --- company ---
    logo = ClarusLogo(11 * mm_())
    right = [_p(co["name"], 14, True, BRAND_C, TA_RIGHT)] + [_p(x, 7, color=MUTED, align=TA_RIGHT) for x in co["address_lines"]] + [
        _p(f"GSTIN: {co['gstin']}   State: [{co['state_code']}] {co['state']}   PAN: {co['pan']}   CIN: {co['cin']}",
           7, color=MUTED, align=TA_RIGHT)]
    head = Table([[logo, right]], colWidths=[logo.width + 6, WIDTH - logo.width - 6])
    head.setStyle(_style(("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
                         ("LINEBELOW", (0, 0), (-1, 0), 1.2, BRAND_C), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)))
    title = inv["title"] + ("" if inv["status"] == "issued" else " — DRAFT" if inv["status"] == "draft" else " — CANCELLED")
    tb = Table([[_p(title, 11.5, True, colors.white)]], colWidths=[WIDTH])
    tb.setStyle(_style(("BACKGROUND", (0, 0), (-1, -1), BAR_C)))
    body += [head, Spacer(1, 4), tb]
    if inv.get("irn") or inv.get("ack_no"):
        irn = Table([[_p(f"IRN: {inv.get('irn') or '-'}", 7, width=WIDTH * 0.7),
                      _p(f"ACK: {inv.get('ack_no') or '-'}  {inv.get('ack_date') or ''}", 7, align=TA_RIGHT)]],
                    colWidths=[WIDTH * 0.7, WIDTH * 0.3])
        irn.setStyle(_style())
        body.append(irn)
    body.append(Spacer(1, 4))

    # --- customer | invoice details ---
    lw, rw = WIDTH * 0.56, WIDTH * 0.44
    cust = [[_p("CUSTOMER", 8, True, colors.white)], [_p(cu.get("name", ""), 9.5, True, width=lw)]]
    if cu.get("address"):
        cust.append([_p(cu["address"], 7.5)])
    cust.append([_p(f"PAN: {cu.get('pan') or '-'}    GSTIN: {cu.get('gstin') or '-'}    "
                    f"State: [{cu.get('state_code') or '-'}] {cu.get('state_name') or ''}", 7.5)])
    ct = Table(cust, colWidths=[lw - 4])
    ct.setStyle(_style(("BACKGROUND", (0, 0), (0, 0), BAR_C), ("TOPPADDING", (0, 1), (-1, -1), 1),
                       ("BOTTOMPADDING", (0, 1), (-1, -1), 1)))
    kv = [("Invoice No.", inv["number"] or "(given on issue)"), ("Invoice Date", _date(inv["invoice_date"])),
          ("Due Date", _date(inv["due_date"])), ("Place of Supply", inv["place_of_supply"] or "-"),
          ("Job Number", h.get("job_number") or "-"), ("Job Type", h.get("job_type") or "-")]
    rt = Table([[_p("INVOICE", 8, True, colors.white), ""]] +
               [[_p(k, 7.5, True), _p(v, 8 if k == "Invoice No." else 7.5, k == "Invoice No.", width=rw * 0.6)] for k, v in kv],
               colWidths=[rw * 0.4, rw * 0.6])
    rt.setStyle(_style(("BACKGROUND", (0, 0), (-1, 0), BAR_C), ("SPAN", (0, 0), (-1, 0)),
                       ("TOPPADDING", (0, 1), (-1, -1), 1), ("BOTTOMPADDING", (0, 1), (-1, -1), 1)))
    two = Table([[ct, rt]], colWidths=[lw, rw])
    two.setStyle(_style(("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0)))
    body += [two, Spacer(1, 4)]

    # --- shipment block: label / value pairs, three per row ---
    pairs = [(label, h.get(key)) for key, label in inv["header_fields"]]
    cw = WIDTH / 3
    rows = []
    for i in range(0, len(pairs), 3):
        row = []
        for label, value in pairs[i:i + 3]:
            row += [_p(label, 6.8, True, color=MUTED), _p(value or "-", 7.2, width=cw * 0.6)]
        row += [""] * (6 - len(row))
        rows.append(row)
    st = Table(rows, colWidths=[cw * 0.4, cw * 0.6] * 3)
    st.setStyle(_style(("BOX", (0, 0), (-1, -1), 0.4, GRID), ("TOPPADDING", (0, 0), (-1, -1), 2),
                       ("BOTTOMPADDING", (0, 0), (-1, -1), 2)))
    body += [st, Spacer(1, 5)]

    # --- lines ---
    intra = inv["intra_state"]
    gst_heads = ["CGST", "SGST"] if intra else ["IGST"]
    heads = ["Sr", "Description", "SAC", "Type", "Non-GST (Rs.)", "Taxable (Rs.)", "GST %"] + \
            [f"{g} (Rs.)" for g in gst_heads] + ["Total (Rs.)"]
    fr = [0.04, 0.30, 0.08, 0.05, 0.11, 0.11, 0.06] + ([0.08, 0.08] if intra else [0.10]) + [0.12]
    k = sum(fr)
    w = [WIDTH * f / k for f in fr]
    rows = [[_p(x, 6.8, True, align=TA_CENTER, width=w[i]) for i, x in enumerate(heads)]]
    for ln in inv["lines"]:
        desc = ln["description"] + (f"\n{ln['sub_description']}" if ln.get("sub_description") else "")
        tax_cells = [ln["cgst"], ln["sgst"]] if intra else [ln["igst"]]
        rows.append([_p(ln["sr"], 7.5, align=TA_CENTER), _p(desc.replace("\n", " — "), 7.5), _p(ln.get("sac") or "", 7.5, width=w[2]),
                     _p(ln.get("tax_type") or "", 7.5, align=TA_CENTER),
                     _p(num(ln["non_gst_value"]) if float(ln["non_gst_value"]) else "", 7.5, align=TA_RIGHT, width=w[4]),
                     _p(num(ln["taxable_value"]) if float(ln["taxable_value"]) else "", 7.5, align=TA_RIGHT, width=w[5]),
                     _p(ln["gst_rate"] if float(ln["taxable_value"]) else "", 7.5, align=TA_RIGHT)] +
                    [_p(num(x) if x and float(x) else "", 7.5, align=TA_RIGHT, width=w[7]) for x in tax_cells] +
                    [_p(num(ln["total"]), 7.5, align=TA_RIGHT, width=w[-1])])
    half_tax = [num(float(t["sub_tax"]) / 2), num(float(t["sub_tax"]) - round(float(t["sub_tax"]) / 2, 2))] if intra else [num(t["sub_tax"])]
    rows.append([_p("T: Taxable  P: Pure Agent  E: Exemption  R: Reverse Charge  N: Non Taxable", 6.5, color=MUTED), "",
                 _p("Sub Total", 7.5, True, align=TA_RIGHT), "",
                 _p(num(t["sub_non_gst"]), 7.5, True, align=TA_RIGHT, width=w[4]),
                 _p(num(t["sub_taxable"]), 7.5, True, align=TA_RIGHT, width=w[5]), ""] +
                [_p(x, 7.5, True, align=TA_RIGHT, width=w[7]) for x in half_tax] +
                [_p(num(t["sub_total"]), 7.5, True, align=TA_RIGHT, width=w[-1])])
    last = len(rows) - 1
    lt = Table(rows, colWidths=w, repeatRows=1)
    lt.setStyle(_style(("BACKGROUND", (0, 0), (-1, 0), HEAD_C), ("GRID", (0, 0), (-1, -1), 0.3, GRID),
                       ("SPAN", (0, last), (1, last)), ("SPAN", (2, last), (3, last)),
                       ("BACKGROUND", (0, last), (-1, last), SUB_C),
                       ("VALIGN", (0, 1), (-1, -1), "TOP")))
    body += [lt, Spacer(1, 5)]

    # --- SAC summary + bank | totals ---
    lw2, rw2 = WIDTH * 0.52, WIDTH * 0.48
    sac_rows = [[_p(x, 6.8, True, align=TA_CENTER) for x in ["SAC/HSN", "%", "Taxable (Rs.)", "GST (Rs.)"]]]
    sac_rows += [[_p(s["sac"], 7.2), _p(s["rate"], 7.2, align=TA_RIGHT), _p(num(s["taxable"]), 7.2, align=TA_RIGHT),
                  _p(num(s["tax"]), 7.2, align=TA_RIGHT)] for s in inv["sac_summary"]] or [[_p("No taxable charges", 7, color=MUTED), "", "", ""]]
    sac = Table(sac_rows, colWidths=[lw2 * f for f in (0.28, 0.14, 0.3, 0.28)])
    sac.setStyle(_style(("BACKGROUND", (0, 0), (-1, 0), HEAD_C), ("GRID", (0, 0), (-1, -1), 0.3, GRID)))
    bank = Table([[_p(k, 7.2, True), _p(v, 7.2)] for k, v in inv["bank"]], colWidths=[lw2 * 0.35, lw2 * 0.65])
    bank.setStyle(_style(("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)))
    left = Table([[sac], [Spacer(1, 3)], [_p("BANK DETAILS", 7.5, True, color=BAR_C)], [bank]], colWidths=[lw2])
    left.setStyle(_style(("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)))
    tot = [("Total Amount Before Tax", t["before_tax"]), ("Add: GST", t["gst"]), ("Total Invoice Value", t["invoice_value"]),
           ("Less: Advance Received", t["advance_received"]), ("Round-Off", t["round_off"]),
           ("Net Payable", t["net_payable"]), ("Tax Payable on Reverse Charges", t["reverse_charge"])]
    tr = Table([[_p(k, 7.8, k == "Net Payable", align=TA_RIGHT), _p("INR " + num(v), 8 if k != "Net Payable" else 9,
                 k == "Net Payable", align=TA_RIGHT, width=rw2 * 0.4)] for k, v in tot], colWidths=[rw2 * 0.6, rw2 * 0.4])
    tr.setStyle(_style(("BACKGROUND", (0, 5), (-1, 5), SUB_C), ("LINEABOVE", (0, 5), (-1, 5), 0.6, BAR_C),
                       ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)))
    both = Table([[left, tr]], colWidths=[lw2, rw2])
    both.setStyle(_style(("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                         ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("LEFTPADDING", (1, 0), (1, 0), 8)))
    words = Table([[_p("Net Payable in Words (INR)", 7.5, True), _p(t["in_words"], 7.8)]],
                  colWidths=[WIDTH * 0.22, WIDTH * 0.78])
    words.setStyle(_style(("BOX", (0, 0), (-1, -1), 0.4, GRID)))
    body += [both, Spacer(1, 4), words]
    if inv.get("remarks"):
        body += [Spacer(1, 3), _p(f"Remarks: {inv['remarks']}", 7.5)]

    # --- terms | signature ---
    terms = [[_p("Terms & Conditions", 7.5, True)]] + [[_p("• " + x, 6.8, color=MUTED)] for x in inv["terms"]]
    tt = Table(terms, colWidths=[WIDTH * 0.62])
    tt.setStyle(_style(("TOPPADDING", (0, 0), (-1, -1), 0.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5)))
    sign = Table([[_p(f"For {co['name']}", 8, True, align=TA_RIGHT)], [Spacer(1, 26)],
                  [_p("Authorised Signatory", 7.5, color=MUTED, align=TA_RIGHT)]], colWidths=[WIDTH * 0.38])
    sign.setStyle(_style())
    foot = Table([[tt, sign]], colWidths=[WIDTH * 0.62, WIDTH * 0.38])
    foot.setStyle(_style(("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                         ("RIGHTPADDING", (0, 0), (-1, -1), 0)))
    body += [Spacer(1, 6), foot]

    doc.build([KeepInFrame(WIDTH, HEIGHT - 2, body, mode="shrink")])
    return buf.getvalue()


def mm_():
    from reportlab.lib.units import mm
    return mm
