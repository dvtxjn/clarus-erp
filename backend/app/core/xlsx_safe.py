"""Excel exports never run text as a formula: a value like "=HYPERLINK(…)" typed into a client
name or BL would otherwise execute when the sheet is opened. Such text gets a leading apostrophe."""
from __future__ import annotations



def defuse(wb) -> None:
    """Call just before saving. Our sheets hold plain values only (no real formulas)."""
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.data_type == "f" and isinstance(c.value, str):  # openpyxl: any text starting "="
                    c.value = "'" + c.value
                    c.data_type = "s"
