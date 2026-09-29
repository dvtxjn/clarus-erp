"""PDF copy of the proforma in the template's look (reportlab), always ONE A4 page.

- Never breaks a word: long values (MBL, names) shrink their font to fit the cell
  instead of wrapping mid-word; sentences wrap at spaces.
- Fits one page: the whole invoice sits in a KeepInFrame that scales it down
  uniformly when a proforma has many lines.
- Clarus logo (wordmark + arrow in brand orange) in the header.
The standard PDF fonts have no ₹ glyph, so amounts print as 'Rs.' with Indian grouping.
"""
from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Flowable, KeepInFrame, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.invoice.company import BAR, BRAND, HEADER, HIGHLIGHT, SUBTOTAL

BAR_C, HEAD_C, SUB_C, BRAND_C, HIGH_C = (colors.HexColor("#" + c) for c in (BAR, HEADER, SUBTOTAL, BRAND, HIGHLIGHT))
GRID = colors.HexColor("#CFC6BE")
TEXT = colors.HexColor("#1A1A1A")
MUTED = colors.HexColor("#595959")
MARGIN = 11 * mm
WIDTH = A4[0] - 2 * MARGIN
HEIGHT = A4[1] - 2 * MARGIN
PAD = 3  # cell padding (pt)


def inr(v) -> str:
    """1,08,560.00 style."""
    if v in (None, ""):
        return "-"
    d = Decimal(v).quantize(Decimal("0.01"))
    sign, (whole, frac) = ("-" if d < 0 else ""), f"{abs(d):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        whole = ",".join(([head] if head else []) + groups + [tail])
    return f"{sign}Rs. {whole}.{frac}"


def num(v) -> str:
    return inr(v).replace("Rs. ", "")


def _date(iso):
    return date.fromisoformat(iso).strftime("%d-%b-%Y") if iso else "-"


def _clean(text) -> str:
    return str(text).replace("₹", "Rs. ")  # no ₹ glyph in the standard PDF fonts


def _p(text, size=8, bold=False, color=TEXT, align=None, width=None):
    """A paragraph that wraps only between words. With `width`, any single word
    wider than the cell shrinks the font until it fits (nothing is cut)."""
    text = _clean(text)
    font = "Helvetica-Bold" if bold else "Helvetica"
    if width:
        longest = max((stringWidth(w, font, size) for w in text.split()), default=0)
        while longest > width - 2 * PAD and size > 5.5:
            size -= 0.25
            longest = max(stringWidth(w, font, size) for w in text.split())
    style = ParagraphStyle("p", fontName=font, fontSize=size, leading=size * 1.22, textColor=color,
                           alignment=align or 0, splitLongWords=0)
    return Paragraph(text.replace("&", "&amp;").replace("<", "&lt;"), style)


def _style(*extra):
    return TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                       ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                       ("LEFTPADDING", (0, 0), (-1, -1), PAD), ("RIGHTPADDING", (0, 0), (-1, -1), PAD), *extra])


def _bar(text, fill=BAR_C, size=8.5):
    t = Table([[_p(text, size, True, colors.white)]], colWidths=[WIDTH])
    t.setStyle(_style(("BACKGROUND", (0, 0), (-1, -1), fill)))
    return t


class ClarusLogo(Flowable):
    """'clarus' + ↗ arrow in brand orange (same drawing as the app's logo)."""

    def __init__(self, height: float):
        super().__init__()
        self.k = height / 96  # the SVG's viewBox is 400 x 96
        self.font_size = 104 * self.k
        self.text_w = stringWidth("clarus", "Helvetica-Bold", self.font_size)
        self.height = height
        self.width = self.text_w + 4 * self.k + (388 - 331.8) * self.k

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        c, k = self.canv, self.k
        c.setFillColor(BRAND_C)
        c.setFont("Helvetica-Bold", self.font_size)
        c.drawString(0, 12 * k, "clarus")
        x0 = self.text_w + 4 * k - 331.8 * k
        pts = [(334, 4), (388, 4), (388, 58), (377, 58), (377, 22.8), (339.6, 60.2), (331.8, 52.4), (369.2, 15), (334, 15)]
        path = c.beginPath()
        for i, (x, y) in enumerate(pts):
            px, py = x0 + x * k, (96 - y) * k
            path.moveTo(px, py) if i == 0 else path.lineTo(px, py)
        path.close()
        c.drawPath(path, stroke=0, fill=1)


def _header(inv) -> list:
    co = inv["company"]
    right = [_p(co["name"], 15, True, BRAND_C, TA_RIGHT), _p(co["address"], 7, color=MUTED, align=TA_RIGHT),
             _p(co["tax_line"], 7, color=MUTED, align=TA_RIGHT), _p(co["contact_line"], 7, color=MUTED, align=TA_RIGHT)]
    logo = ClarusLogo(12 * mm)
    t = Table([[logo, right]], colWidths=[logo.width + 6, WIDTH - logo.width - 6])
    t.setStyle(_style(("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
                      ("LINEBELOW", (0, 0), (-1, 0), 1.2, BRAND_C), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)))
    title = inv["title"] + (f" — {inv['copy_label'].upper()}" if inv.get("copy_label") else "")
    out = [t, Spacer(1, 5), _bar(title, size=11.5)]
    if inv.get("disclaimer"):
        d = Table([[_p(inv["disclaimer"].upper(), 9.5, True, align=TA_CENTER, width=WIDTH)]], colWidths=[WIDTH])
        d.setStyle(_style(("BACKGROUND", (0, 0), (-1, -1), HIGH_C)))
        out.append(d)
    return out + [Spacer(1, 5)]


def _parties(inv) -> Table:
    from app.invoice.xlsx import _org_lines  # same Bill To detail lines as the Excel copy
    bt, det = inv["bill_to"], inv["details"]
    lw, rw = WIDTH * 0.56, WIDTH * 0.44
    left = [[_p("BILL TO", 8, True, colors.white)], [_p(bt["name"] or "", 10, True, width=lw)]]
    left += [[_p(x, 7.5)] for x in _org_lines(bt.get("organization"))]
    left += [[_p(f"BL Consignee: {bt['bl_consignee'] or '-'}", 7.5)], [_p(f"BE Importer: {bt['be_importer'] or '-'}", 7.5)]]
    if bt.get("hss"):
        left.append([_p(f"HSS: {bt['hss']['seller']} (seller) → {bt['hss']['buyer']} (buyer)", 7.5)])
    lt = Table(left, colWidths=[lw - 4])
    lt.setStyle(_style(("BACKGROUND", (0, 0), (0, 0), BAR_C), ("TOPPADDING", (0, 1), (-1, -1), 1),
                       ("BOTTOMPADDING", (0, 1), (-1, -1), 1)))
    kv = [("Invoice Date", _date(det["invoice_date"])), ("Job", det["job"] or "-"), ("BE No.", det["be_no"] or "-"),
          ("BE Date", _date(det["be_date"])), ("Port", det["port"] or "-")]
    right = [[_p("SHIPMENT DETAILS", 8, True, colors.white), ""]] + [
        [_p(k, 7.5, True), _p(v, 7.5, width=rw * 0.6)] for k, v in kv]
    rt = Table(right, colWidths=[rw * 0.4, rw * 0.6])
    rt.setStyle(_style(("BACKGROUND", (0, 0), (-1, 0), BAR_C), ("SPAN", (0, 0), (-1, 0)),
                       ("TOPPADDING", (0, 1), (-1, -1), 1), ("BOTTOMPADDING", (0, 1), (-1, -1), 1)))
    two = Table([[lt, rt]], colWidths=[lw, rw])
    two.setStyle(_style(("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0)))
    return two


def _grid(heads, values, widths, value_align=TA_CENTER) -> Table:
    t = Table([[_p(h, 7, True, align=TA_CENTER, width=w) for h, w in zip(heads, widths)],
               [_p(v, 8, align=value_align, width=w) for v, w in zip(values, widths)]], colWidths=widths)
    t.setStyle(_style(("BACKGROUND", (0, 0), (-1, 0), HEAD_C), ("GRID", (0, 0), (-1, -1), 0.4, GRID)))
    return t


def _charges(inv) -> list:
    """One table: section bars, lines, subtotals; grand total after the last section
    that counts; value section; Cost Inclusion (not in the total) last."""
    # (no Rate x Qty column — client: too much detail for the print)
    w = [WIDTH * f for f in (0.49, 0.17, 0.16, 0.18)]
    heads = ["Description", "Amount (Rs.)", "GST (Rs.)", "Total (Rs.)"]
    shown = [s for s in inv["sections"] if s["lines"] or (s["counts_in_total"] and s["category"] != "royalty")]
    counted = [s for s in shown if s["counts_in_total"]]
    out: list = []

    def section_table(secs) -> Table:
        rows = [[_p(h, 7.5, True, align=TA_CENTER if i == 0 else TA_RIGHT, width=w[i]) for i, h in enumerate(heads)]]
        style = [("BACKGROUND", (0, 0), (-1, 0), HEAD_C), ("LINEBELOW", (0, 0), (-1, -1), 0.3, GRID)]
        for sec in secs:
            r = len(rows)
            rows.append([_p(sec["title"] + ("" if sec["counts_in_total"] else " — for reference, not in the total"),
                            8, True, colors.white), "", "", ""])
            style += [("SPAN", (0, r), (-1, r)), ("BACKGROUND", (0, r), (-1, r), BAR_C)]
            for li in sec["lines"]:
                rows.append([_p(li["description"], 8),
                             _p(num(li["amount"]), 8, align=TA_RIGHT, width=w[1]),
                             _p(num(li["gst_amount"]), 8, align=TA_RIGHT, width=w[2]),
                             _p(num(li["total"]), 8, align=TA_RIGHT, width=w[3])])
            if not sec["lines"]:
                r2 = len(rows)
                rows.append([_p("No charges", 7.5, color=MUTED), "", "", ""])
                style.append(("SPAN", (0, r2), (-1, r2)))
            r = len(rows)
            rows.append([_p(f"Subtotal — {sec['title']}", 8, True, align=TA_RIGHT), "", "",
                         _p(num(sec["subtotal"]), 8.5, True, align=TA_RIGHT, width=w[3])])
            style += [("SPAN", (0, r), (2, r)), ("BACKGROUND", (0, r), (-1, r), SUB_C)]
        t = Table(rows, colWidths=w)
        t.setStyle(_style(*style))
        return t

    out.append(section_table(counted))
    ro = Decimal(inv.get("round_off") or 0)
    if ro:
        r = Table([[_p("Round off", 7.5, align=TA_RIGHT), _p(("+" if ro > 0 else "−") + num(abs(ro)), 7.5, align=TA_RIGHT)]],
                  colWidths=[WIDTH * 0.78, WIDTH * 0.22])
        r.setStyle(_style())
        out.append(r)
    g = Table([[_p("GRAND TOTAL — " + inv["grand_total_label"].upper(), 9, True, colors.white, TA_RIGHT),
                _p(inr(inv["grand_total"]), 10, True, colors.white, TA_RIGHT, width=WIDTH * 0.22)]],
              colWidths=[WIDTH * 0.78, WIDTH * 0.22])
    g.setStyle(_style(("BACKGROUND", (0, 0), (-1, -1), BRAND_C), ("TOPPADDING", (0, 0), (-1, -1), 4),
                      ("BOTTOMPADDING", (0, 0), (-1, -1), 4)))
    out += [g]
    rest = [s for s in shown if not s["counts_in_total"]]
    if rest:
        out += [Spacer(1, 4), section_table(rest)]
    return out


def _value_grid(inv) -> Table:
    v = inv["value"]
    vals = [num(x) for x in (v["value_of_goods"], v["gst_input"], v["value_per_kg"], v["bill_rate"],
                             v["gst_output"], v["gst_difference"])]
    return _grid(["Value of Goods", "GST Input", "Value / Kg", "Bill Rate (per kg)", "GST Output", "GST Difference"],
                 vals, [WIDTH / 6] * 6, TA_RIGHT)


def _footer(inv) -> Table:
    co = inv["company"]
    half = WIDTH / 2 - 6
    notes = [[_p("NOTES", 8, True, colors.white)]] + [[_p(n, 7.5)] for n in inv["notes"]]
    nt = Table(notes, colWidths=[half])
    nt.setStyle(_style(("BACKGROUND", (0, 0), (-1, 0), BAR_C), ("BACKGROUND", (0, 1), (-1, 1), HIGH_C)))
    bank = [[_p("BANK DETAILS FOR PAYMENT", 8, True, colors.white), ""]] + [
        [_p(k, 7.5, True), _p(val, 7.5, width=half * 0.6)] for k, val in inv["bank"]]
    bt = Table(bank, colWidths=[half * 0.4, half * 0.6])
    bt.setStyle(_style(("BACKGROUND", (0, 0), (-1, 0), BAR_C), ("SPAN", (0, 0), (-1, 0)),
                       ("TOPPADDING", (0, 1), (-1, -1), 1), ("BOTTOMPADDING", (0, 1), (-1, -1), 1)))
    sign = Table([[_p(f"For {co['name']}", 8, True, align=TA_RIGHT)], [Spacer(1, 22)],
                  [_p("Authorised Signatory", 7.5, color=MUTED, align=TA_RIGHT)]], colWidths=[half])
    sign.setStyle(_style())
    t = Table([[nt, bt], ["", sign]], colWidths=[WIDTH / 2, WIDTH / 2])
    t.setStyle(_style(("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                      ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("LEFTPADDING", (1, 0), (1, -1), 6)))
    return t


def render_pdf(inv: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN,
                            bottomMargin=MARGIN, title=f"Proforma Invoice - {inv['bill_to']['name'] or ''}")
    ref = inv["reference"]
    ref_vals = [num(ref["assessable_value"]), ref["mbl"] or "-", ref["hbl"] or ref["hss"], ref["containers"] or "-",
                f"{Decimal(ref['weight_kgs']):,.0f}" if ref["weight_kgs"] else "-", ref["exam_applicable"]]
    ref_w = [WIDTH * f for f in (0.15, 0.25, 0.20, 0.12, 0.14, 0.14)]
    body = [
        *_header(inv),
        _parties(inv), Spacer(1, 5),
        _grid(["Assessable Value", "MBL", "HBL / HSS", "# Containers", "WT (KGS)", "Exam Applicable"], ref_vals, ref_w),
        Spacer(1, 3),
        # value of goods / GST input / bill rate right under the assessable value (client, 2026-09-30)
        _value_grid(inv),
        Spacer(1, 5),
        *_charges(inv),
        Spacer(1, 6),
        _footer(inv),
    ]
    # one A4 page, always: scale the whole invoice down if it's taller than the page
    doc.build([KeepInFrame(WIDTH, HEIGHT - 2, body, mode="shrink")])
    return buf.getvalue()
