import io

from openpyxl import Workbook

from app.extraction.be_pdf import normalize_date, extract_gross_weight_fallback, scan_be_pdf
from app.extraction.cfs_pdf import classify_text, parse_amount, scan_cfs_pdf, match_cfs_to_row
from app.extraction.excel_imports import (
    importer_name_check, load_challan_due_amounts, load_org_repo, split_interest,
)
from tests.conftest import be_pdf, cfs_pdf, make_pdf


# --- pure helpers ---

def test_normalize_date():
    assert normalize_date("05/03/2026") == "05.03.2026"
    assert normalize_date("5-3-26") == "05.03.2026"
    assert normalize_date("05-MAR-2026") == "05.03.2026"
    assert normalize_date("garbage") == "garbage"


def test_parse_amount_indian_grouping():
    assert parse_amount("1,08,560.00") == 108560.0
    assert parse_amount("") is None
    assert parse_amount("abc") is None


def test_gross_weight_fallback():
    assert extract_gross_weight_fallback("... 24500.5 (KGS) G.WT ...") == "24500.5"
    assert extract_gross_weight_fallback("G.WT : 3300") == "3300"


def test_classify():
    assert classify_text("BILL OF ENTRY\n1.IMPORTER NAME") == "BE"
    assert classify_text("CONTAINER FREIGHT STATION\nTotal Amount Before Tax") == "CFS"
    assert classify_text("") == "BE"  # tie -> BE


def test_importer_name_check():
    reg = {"6390001": "ACME TYRES PRIVATE LIMITED"}
    assert importer_name_check("6390001", "ACME TYRES PRIVATE LIMITED", reg) == ("NO", "ACME TYRES PRIVATE LIMITED")
    assert importer_name_check("6390001", "ACME TYRE PVT LTD", reg) == ("YES", "ACME TYRES PRIVATE LIMITED")
    assert importer_name_check("9999999", "X", reg) == ("N/A", "AD Code Not Found")


def test_split_interest():
    assert split_interest(61500.0, 62000.0) == (62000.0, 500.0)


# --- PDFs ---

def test_scan_be_pdf_all_fields():
    r = scan_be_pdf(be_pdf())
    assert r["missing"] == []
    assert r["port_code"] == "INNSA1"
    assert r["be_no"] == "2345678"
    assert r["be_date"] == "05.03.2026"
    assert r["importer_name"] == "ACME TYRES PRIVATE LIMITED"
    assert r["ad_code"] == "6390001"
    assert r["mawb"] == "MEDU1234567890"
    assert r["hawb"] == "HBL998877"
    assert r["cont_count"] == "2"
    assert r["gross_wt"] == "24500.5"
    assert r["tot_ass_val"] == "250000.00"
    assert r["igst"] == "45000.00"
    assert r["tot_amount"] == "61500.00"


def test_scan_be_pdf_bad_file():
    r = scan_be_pdf(io.BytesIO(b"not a pdf"))
    assert "error" in r


def test_scan_be_pdf_flags_missing_critical():
    r = scan_be_pdf(make_pdf([(40, 40, "BILL OF ENTRY")]))
    assert set(r["missing"]) == {"be_no", "importer_name", "mawb", "port_code"}


def test_scan_cfs_pdf_and_sanity():
    r = scan_cfs_pdf(cfs_pdf())
    assert r["be_no"] == "2345678"
    assert r["bl_no"] == "MEDU1234567890"
    assert r["cfs_before_tax"] == 108560.0
    assert r["cfs_gst"] == 19540.8
    assert r["cfs_after_tax"] == 128100.8
    assert r["cfs_sanity_ok"] is True
    assert scan_cfs_pdf(cfs_pdf(after="1,50,000.00"))["cfs_sanity_ok"] is False


def test_match_cfs_be_then_bl():
    rows = [{"be_no": "111", "mawb": "AAA"}, {"be_no": "222", "mawb": "BBB"}]
    assert match_cfs_to_row({"be_no": "222"}, rows) == (1, "BE Number")
    assert match_cfs_to_row({"be_no": "999", "bl_no": "aaa"}, rows) == (0, "BL Number")
    assert match_cfs_to_row({"be_no": "999", "bl_no": "ZZZ"}, rows) == (None, None)


# --- Excel ---

def _xlsx(build):
    wb = Workbook()
    build(wb)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_challan_filters_be_and_flags_dupes():
    def build(wb):
        ws = wb.active
        ws.append(["IEC", "Location Code", "Doc type", "Doc no.", "Doc date", "Challan no.", "Due Amount"])
        ws.append(["X", "INNSA1", "BE", 2345678.0, "05/03/2026", "C1", 62000])
        ws.append(["X", "INNSA1", "SB", 1111111, "05/03/2026", "C2", 999])
        ws.append(["X", "INNSA1", "BE", "3456789", "05/03/2026", "C3", 100])
        ws.append(["X", "INNSA1", "BE", "3456789", "05/03/2026", "C4", 150])
    due, note = load_challan_due_amounts(_xlsx(build))
    assert due == {"2345678": 62000.0, "3456789": 150.0}
    assert "1 BE number" in note


def test_challan_missing_columns():
    due, note = load_challan_due_amounts(_xlsx(lambda wb: wb.active.append(["foo", "bar"])))
    assert due == {} and "Doc no." in note


def test_org_repo_header_on_row_3_and_inactive_skipped():
    def build(wb):
        ws = wb.active
        ws.title = "Organization List"
        ws.append(["Organization List export"])
        ws.append([])
        ws.append(["Organization", "AD Code", "Is Active"])
        ws.append(["ACME TYRES PRIVATE LIMITED", "6390001", True])
        ws.append(["OLD CO LTD", "6390002", False])
        ws.append(["BAD CODE LTD", "12", True])
    assert load_org_repo(_xlsx(build)) == {"6390001": "ACME TYRES PRIVATE LIMITED"}


def test_symbol_font_characters_are_decoded():
    from app.extraction.be_pdf import clean_pdf_text
    shifted = "".join(chr(0xF000 + ord(c)) for c in "BOE No : 3401995")
    assert clean_pdf_text(shifted) == "BOE No : 3401995"
    assert clean_pdf_text("normal ₹ text") == "normal ₹ text"


def test_org_export_all_columns():
    """The filing software's real export layout (OrganizationRepository_*.xlsx): 2 title rows,
    header on row 3, address split over Branch AD1-3 / City / State / Postal Code / Country."""
    from openpyxl import Workbook
    import io
    from app.extraction.excel_imports import load_org_details
    wb = Workbook()
    ws = wb.active
    ws.title = "Organization List"
    head = ["Organization", "ALIAS", "Branch AD1", "Branch AD2", "Branch AD3", "City", "State", "Postal Code",
            "Country", "Email Address", "Telephone No", "AD Code", "Is Active", "IE CODE NO", "PAN NO", "GSTIN"]
    ws.append(["CLARUS LOGISTICS LLP"] * len(head))
    ws.append(["Organization List"] * len(head))
    ws.append(head)
    ws.append(["AGARWAL RUBBER", "", "SURVEY NO 1115/8 , PAIKI, 2nd Floor", "Office 212, Lord Shiva Building, Morbi", "",
               "Morbi", "Gujarat", "363641", "INDIA", "", "", "0010191", "True", "", "ACCFA6289R", "24ACCFA6289R1ZQ"])
    ws.append(["AHS RECYCLING INC", "", "9303 CANNIFF STREET", "HOUSTON", "", "Houston", "Texas", "77017",
               "UNITED STATES", "", "", "", "True", "", "", ""])
    buf = io.BytesIO()
    wb.save(buf)
    orgs = {o["name"]: o for o in load_org_details(io.BytesIO(buf.getvalue()))}
    a = orgs["AGARWAL RUBBER"]
    assert a["address"] == "SURVEY NO 1115/8 , PAIKI, 2nd Floor, Office 212, Lord Shiva Building, Morbi, Morbi, Gujarat - 363641"
    assert (a["ad_code"], a["gstin"], a["pan"], a["state"]) == ("0010191", "24ACCFA6289R1ZQ", "ACCFA6289R", "Gujarat")
    assert orgs["AHS RECYCLING INC"]["ad_code"] is None and "UNITED STATES" in orgs["AHS RECYCLING INC"]["address"]
