"""
ICEGATE public enquiry — Sea IGM (client's playwright_igm_v2.py, ported, 2026-09-30).

Input: MBL number + port code (e.g. INNSA1). Output: whether the IGM is filed and, when it is, the IGM
no / date, inward date, line no, voyage, MBL / HBL no + date, gross weight (+ unit), packages, package
code and the containers. Read-only: it only looks things up on the public enquiry page.
"""
import time
from typing import Optional

URL = "https://foservices.icegate.gov.in/#/public-enquiries/document-status/sea-igm"

NA = {"", "n.a.", "na", "-", "pending"}


def _clean(v: str) -> Optional[str]:
    v = (v or "").strip()
    return None if v.lower() in NA else v


def _date_part(v: str) -> Optional[str]:
    return _clean((v or "").split(" ")[0])


def _cell(row: list, i: int) -> str:
    return row[i] if len(row) > i else ""


def _click(page, selector: str) -> None:
    """Normal click, or a JS click when Angular's overlay gets in the way (the ng-select often does)."""
    try:
        page.click(selector, timeout=8000)
    except Exception:
        page.eval_on_selector(selector, "el => el.click()")


def _tables(page) -> list[dict]:
    return page.eval_on_selector_all(
        "table",
        """tables => tables.map(t => ({
            headers: Array.from(t.querySelectorAll("thead th")).map(th => th.innerText.trim()),
            rows: Array.from(t.querySelectorAll("tbody tr")).map(r =>
                Array.from(r.querySelectorAll("td")).map(td => td.innerText.trim()))
        }))""",
    )


def _wait_rows(page, index: int, tries: int = 20) -> None:
    """Poll until table #index has rows (ICEGATE fills them after its own XHRs)."""
    for _ in range(tries):
        counts = page.eval_on_selector_all("table", "ts => ts.map(t => t.querySelectorAll('tbody tr').length)")
        if len(counts) > index and counts[index] > 0:
            return
        time.sleep(1)


def lookup(page, mbl: str, port: str) -> dict:
    """One MBL on an open Playwright page. Returns {"status": "IGM Not Filed"} or the full details."""
    for attempt in range(5):
        try:
            page.goto(URL, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=30000)
            page.reload()
            page.wait_for_load_state("networkidle", timeout=30000)
            break
        except Exception:
            if attempt == 4:
                raise
            time.sleep(3)

    page.wait_for_selector('input[placeholder="Enter Master BL No"]', timeout=15000)
    page.fill('input[placeholder="Enter Master BL No"]', mbl)
    _click(page, "ng-select")
    page.wait_for_selector("ng-select input", timeout=10000)
    page.fill("ng-select input", port)
    page.wait_for_selector(f'.ng-option:has-text("{port}")', timeout=10000)
    _click(page, f'.ng-option:has-text("{port}")')
    page.wait_for_selector("button.btn-grey", timeout=10000)
    _click(page, "button.btn-grey")

    # any table after searching = the IGM is filed
    try:
        page.wait_for_selector("table", timeout=20000)
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        return {"status": "IGM Not Filed"}
    bl_rows = page.eval_on_selector_all(
        "table tbody tr", 'rows => rows.map(r => Array.from(r.querySelectorAll("td")).map(td => td.innerText.trim()))'
    )
    if not bl_rows or not bl_rows[0]:
        return {"status": "IGM Not Filed"}

    bl = bl_rows[0]
    out = {
        "status": "IGM Filed",
        "line_no": _clean(_cell(bl, 1)),
        "mbl_no": _clean(_cell(bl, 3)),
        "mbl_date": _date_part(_cell(bl, 4)),
        "hbl_no": _clean(_cell(bl, 5)),
        "hbl_date": _date_part(_cell(bl, 6)),
        "gross_weight": _clean(_cell(bl, 8)),
        "unit_weight": _clean(_cell(bl, 9)),
        "total_package": _clean(_cell(bl, 10)),
        "package_code": _clean(_cell(bl, 11)),
        "igm_no": None, "igm_date": None, "inw_date": None, "voyage_no": None,
        "containers": [],
    }

    # "View" → the IGM table (index 1)
    _click(page, "table tbody tr:first-child td:last-child")
    page.wait_for_load_state("networkidle", timeout=15000)
    time.sleep(2)
    _wait_rows(page, 1)
    tables = _tables(page)
    if len(tables) < 2 or not tables[1]["rows"]:
        return out
    igm = tables[1]["rows"][0]
    out.update(
        igm_no=_clean(_cell(igm, 1)),
        igm_date=_date_part(_cell(igm, 2)),
        inw_date=_date_part(_cell(igm, 3)),
        voyage_no=_clean(_cell(igm, 6)),
    )

    # "Container Details" → the container table (index 2)
    try:
        _click(page, 'td:has-text("Container Details")')
        page.wait_for_load_state("networkidle", timeout=15000)
        time.sleep(2)
        _wait_rows(page, 2)
        tables = _tables(page)
        if len(tables) >= 3:
            out["containers"] = [
                {"container": _cell(r, 4), "status": _cell(r, 5)} for r in tables[2]["rows"] if len(r) > 5
            ]
    except Exception:
        pass  # details are a bonus; the IGM itself is already in
    return out


def fetch(mbl: str, port: str, headless: bool = True) -> dict:
    """Open a browser (the Mac's Chrome locally), look one MBL up, close."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=headless)
        except Exception:
            browser = p.chromium.launch(headless=headless)  # a downloaded Chromium (servers)
        try:
            page = browser.new_page()
            return lookup(page, mbl, port)
        finally:
            browser.close()
