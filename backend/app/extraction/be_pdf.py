"""
Bill of Entry PDF extraction — ported from reference/be_expense_sheet.py v7.2
(normalize_date, extract_mawb_hawb, extract_ad_code, extract_pkg_gw,
extract_gross_weight_fallback, scan_pdf). Regexes, anchor offsets and
fallback order are kept verbatim; the only structural change is that the PDF
is opened once and its text/words are passed to the helpers, instead of each
helper re-opening the file from disk.
"""
from __future__ import annotations

import re
from typing import Any, BinaryIO, Optional, Tuple, Union

import pdfplumber

PdfSource = Union[str, BinaryIO]

# PDFs made with "Microsoft Print to PDF" (and some other drivers) embed
# symbol-encoded fonts: every character comes out shifted into the Private
# Use Area, e.g. "IMPORT" as U+F049 U+F04D ... Shifting back by 0xF000
# recovers the real text. Seen on Navkar CFS tax invoices.
_SHIFTED_CHARS = re.compile("[\uf020-\uf0ff]")


def clean_pdf_text(text: str) -> str:
    return _SHIFTED_CHARS.sub(lambda m: chr(ord(m.group()) - 0xF000), text) if text else text


def read_pdf(pdf) -> Tuple[list, list]:
    """(page texts, page-1 words) from an open pdfplumber PDF, with shifted
    symbol-font characters decoded."""
    pages = [clean_pdf_text(p.extract_text() or "") for p in pdf.pages]
    words = [{**w, "text": clean_pdf_text(w["text"])} for w in pdf.pages[0].extract_words()] if pdf.pages else []
    return pages, words

MONTH_MAP = {
    'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04',
    'MAY': '05', 'JUN': '06', 'JUL': '07', 'AUG': '08',
    'SEP': '09', 'OCT': '10', 'NOV': '11', 'DEC': '12',
}


def normalize_date(token: Optional[str]) -> Optional[str]:
    """'05/03/2026', '05-03-26', '05-MAR-2026' -> '05.03.2026'."""
    if not token:
        return token
    token = token.strip().replace("-", "/")
    parts = token.split("/")
    if len(parts) == 3:
        d, m, y = parts
        if len(y) == 2:
            y = "20" + y
        if m.upper() in MONTH_MAP:
            m = MONTH_MAP[m.upper()]
        try:
            return f"{int(d):02d}.{int(m):02d}.{y}"
        except ValueError:
            return token
    return token


def extract_mawb_hawb(words: list) -> Tuple[Optional[str], Optional[str]]:
    """MAWB/HAWB (= MBL/HBL) by word position under the manifest header row
    '6.MAWB NO  7.DATE  8.HAWB NO  9.DATE ...' on page 1."""
    mawb_header = hawb_header = None
    for w in words:
        t = w['text'].upper()
        if 'MAWB' in t and mawb_header is None:
            mawb_header = w
        if 'HAWB' in t and hawb_header is None:
            hawb_header = w

    if not mawb_header:
        return None, None

    header_y = mawb_header['top']
    mawb_x0 = mawb_header['x0']
    hawb_x0 = hawb_header['x0'] if hawb_header else mawb_x0 + 150
    mawb_right = hawb_x0
    hawb_right = hawb_x0 + 120

    for w in words:
        if abs(w['top'] - header_y) < 5:
            if w['text'].upper() in ('7.DATE', '7DATE') and mawb_x0 < w['x0'] < hawb_x0:
                mawb_right = w['x0']
            if w['text'].upper() in ('9.DATE', '9DATE') and w['x0'] > hawb_x0:
                hawb_right = w['x0']

    data_words = [w for w in words if header_y + 5 < w['top'] < header_y + 35]

    mawb_words = sorted([w for w in data_words if w['x0'] >= mawb_x0 - 10 and w['x1'] <= mawb_right + 10],
                        key=lambda w: (w['top'], w['x0']))
    hawb_words = sorted([w for w in data_words if w['x0'] >= hawb_x0 - 10 and w['x1'] <= hawb_right + 10],
                        key=lambda w: (w['top'], w['x0']))

    def smart_concat(word_list):
        # A long MBL can wrap onto a second line inside its column; rejoin it.
        if not word_list:
            return None
        rows, current_row, current_y = [], [word_list[0]['text']], word_list[0]['top']
        for i in range(1, len(word_list)):
            if abs(word_list[i]['top'] - current_y) < 4:
                current_row.append(word_list[i]['text'])
            else:
                rows.append(''.join(current_row))
                current_row = [word_list[i]['text']]
                current_y = word_list[i]['top']
        rows.append(''.join(current_row))
        if len(rows) == 1:
            return rows[0]
        r0, r1 = rows[0], rows[1]
        if re.match(r'^[A-Z]{2,}[A-Z0-9]*$', r0) and re.fullmatch(r'\d+', r1):
            return r0 + r1
        if re.fullmatch(r'\d+', r0) and re.fullmatch(r'\d+', r1):
            return r0 + r1
        if re.match(r'^[A-Z0-9]+$', r0) and re.match(r'^[A-Z0-9]+$', r1):
            return r0 + r1
        return r0

    def clean(value):
        if not value:
            return None
        value = re.sub(r'\d{2}/\d{2}/\d{4}.*$', '', value).strip().strip('/')
        # Some layouts (Gate Pass) print the headings where the values go: "/MAWBDT", "/HAWBDT".
        # A B/L number always has a digit and is never a heading word.
        if re.search(r'MAWB|HAWB|DATE', value.upper()) or not re.search(r'\d', value):
            return None
        return value if len(value) >= 4 else None

    return clean(smart_concat(mawb_words)), clean(smart_concat(hawb_words))


def extract_ad_code(text: str) -> Optional[str]:
    match = re.search(r'AD\s*CODE[\s\S]{0,50}?\b(\d{7})\b', text.upper())
    return match.group(1) if match else None


def extract_pkg_gw(words: list) -> Tuple[Optional[str], Optional[str]]:
    """PKG count and Gross Weight (KGS), anchored to the same manifest header
    row as MAWB/HAWB: '... 9.DATE  10.PKG  11.GW'."""
    mawb_header = hawb_header = pkg_header = gw_header = None
    for w in words:
        t = w['text'].upper().replace('.', '')
        if 'MAWB' in t and mawb_header is None:
            mawb_header = w
        if 'HAWB' in t and hawb_header is None:
            hawb_header = w
        if t in ('PKG', '10PKG') and pkg_header is None:
            pkg_header = w
        if t in ('GW', '11GW') and gw_header is None:
            gw_header = w

    if not mawb_header:
        return None, None

    header_y = mawb_header['top']

    # Only trust a PKG/GW header on the SAME row as MAWB.
    if pkg_header and abs(pkg_header['top'] - header_y) > 5:
        pkg_header = None
    if gw_header and abs(gw_header['top'] - header_y) > 5:
        gw_header = None

    hawb_x0 = hawb_header['x0'] if hawb_header else mawb_header['x0'] + 150
    pkg_x0 = pkg_header['x0'] if pkg_header else hawb_x0 + 220
    gw_x0 = gw_header['x0'] if gw_header else pkg_x0 + 60

    pkg_right = gw_x0
    gw_right = gw_x0 + 100

    data_words = [w for w in words if header_y + 5 < w['top'] < header_y + 35]

    pkg_words = sorted([w for w in data_words if pkg_x0 - 10 <= w['x0'] <= pkg_right + 10],
                       key=lambda w: (w['top'], w['x0']))
    gw_words = sorted([w for w in data_words if gw_x0 - 10 <= w['x0'] <= gw_right + 10],
                      key=lambda w: (w['top'], w['x0']))

    def first_number(word_list):
        for w in word_list:
            m = re.search(r'\d+(?:\.\d+)?', w['text'])
            if m:
                return m.group(0)
        return None

    return first_number(pkg_words), first_number(gw_words)


def extract_gross_weight_fallback(text: str) -> Optional[str]:
    """Used only if extract_pkg_gw() finds nothing: the number beside a
    'G.WT' / 'GROSS WT' label in the linear text."""
    m = re.search(r'(\d{2,7}(?:\.\d+)?)\s*(?:\([A-Z]*\))?\s*G\.?\s*WT', text.upper())
    if m:
        return m.group(1)
    m = re.search(r'G\.?\s*WT[^\d]{0,20}?(\d{2,7}(?:\.\d+)?)', text.upper())
    if m:
        return m.group(1)
    return None


def extract_importer_name(text: str) -> Optional[str]:
    # Strategy 1: lines after the label, skipping single-char watermark artifacts
    block = re.search(r'1\.IMPORTER\s+NAME[^\n]*\n([\s\S]{0,300})', text)
    if block:
        for line in block.group(1).splitlines()[:6]:
            candidate = line.strip().replace('"', '').replace(',', '').strip()
            candidate = re.sub(r'\s+[A-Z]$', '', candidate).strip()
            if candidate and len(candidate) > 5 and not re.match(r'^[\d\.\s]+$', candidate):
                return candidate

    # Strategy 2: name on the SAME line as the label
    same_line = re.search(
        r'1\.IMPORTER\s+NAME\s*(?:&\s*ADDRESS)?\s{2,}([A-Z][A-Z\s&/().,\-]+(?:LIMITED|LTD|PVT|PRIVATE|CORPORATION|CORP|INC|LLC|COMPANY|CO\b)[^\n]*)',
        text, re.IGNORECASE,
    )
    if same_line:
        return same_line.group(1).strip()

    # Strategy 3: an all-caps company name somewhere in the block after the label
    loose = re.search(r'1\.IMPORTER\s+NAME[\s\S]{0,200}?([A-Z]{2}[A-Z\s&/().,\-]{10,}(?:LIMITED|LTD|PRIVATE|PVT))', text)
    if loose:
        return loose.group(1).strip()
    return None


def extract_container_count(text: str) -> str:
    iso_containers = set(re.findall(r'\b[A-Z]{4}\d{7}\b', text))
    if iso_containers:
        return str(len(iso_containers))
    first_part = text[:3000]
    cleaned = re.sub(r'\s+', ' ', first_part)
    tm = re.search(r'Nos\s*"\s*,\s*"\s*\d+\s*"\s*,\s*"\s*\d+(?:\s+|\s*\\n\s*)(\d+)\s*"', cleaned)
    if tm:
        return tm.group(1)
    cn = re.search(r'CONT[\s\S]{0,100}?\b(\d+)\b', first_part)
    return cn.group(1) if cn else "0"


def extract_duty_summary(text: str) -> dict:
    """Assessable value / IGST from the line(s) under the '1.BCD ... 18.TOT.ASS VAL'
    header, total duty from under '9.SG ... 19.TOT. AMOUNT'."""
    out = {"tot_ass_val": None, "igst": None, "tot_amount": None}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "1.BCD" in line and "18.TOT.ASS VAL" in line:
            for offset in (1, 2):
                if i + offset < len(lines):
                    nums = re.findall(r'\d+(?:\.\d+)?', lines[i + offset])
                    if len(nums) >= 3:
                        out["tot_ass_val"] = nums[-1]
                        out["igst"] = nums[-3]
                        break
        if "9.SG" in line and "19.TOT. AMOUNT" in line:
            for offset in (1, 2):
                if i + offset < len(lines):
                    nums = re.findall(r'\d+(?:\.\d+)?', lines[i + offset])
                    if nums:
                        out["tot_amount"] = nums[-1]
                        break
    return out


def scan_be_text(text: str, first_page_words: list) -> dict[str, Any]:
    """All BE fields from already-extracted text + page-1 words."""
    result: dict[str, Any] = {}

    port_match = re.search(r'\b(IN[A-Z]{3}\d)\b', text)
    result["port_code"] = port_match.group(1) if port_match else None

    result["be_no"] = None
    if result["port_code"]:
        m = re.search(result["port_code"] + r'[\s,"]+(\d{7})', text)
        if m:
            result["be_no"] = m.group(1)
    if not result["be_no"]:
        all7 = re.findall(r'\b(\d{7})\b', text)
        result["be_no"] = all7[0] if all7 else None

    date_matches = re.findall(r'\b(\d{2}/\d{2}/\d{4}|\d{2}-\d{2}-\d{4}|\d{2}-[A-Z]{3}-\d{2,4})\b', text)
    result["be_date"] = normalize_date(date_matches[0]) if date_matches else None

    result["importer_name"] = extract_importer_name(text)
    result["cont_count"] = extract_container_count(text)
    result["mawb"], result["hawb"] = extract_mawb_hawb(first_page_words)
    result["ad_code"] = extract_ad_code(text)

    _, gross_wt = extract_pkg_gw(first_page_words)
    result["gross_wt"] = gross_wt or extract_gross_weight_fallback(text)

    result.update(extract_duty_summary(text))
    return result


# Fields the reference tool flags red when missing (print_extraction_results)
CRITICAL_BE_FIELDS = ("be_no", "importer_name", "mawb", "port_code")


def scan_be_pdf(source: PdfSource) -> dict[str, Any]:
    """Scan a Bill of Entry PDF. Never raises — a read failure comes back as
    result['error']; missing critical fields are listed in result['missing']."""
    try:
        with pdfplumber.open(source) as pdf:
            pages, words = read_pdf(pdf)
    except Exception as e:  # corrupt / encrypted / not a PDF
        return {"error": str(e)}
    text = "\n".join(pages)

    result = scan_be_text(text, words)
    result["missing"] = [f for f in CRITICAL_BE_FIELDS if not result.get(f)]
    return result
