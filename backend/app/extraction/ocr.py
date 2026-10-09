"""
OCR for scanned uploads (free, on our own server: RapidOCR + ONNX runtime, Apache-2.0 —
no outside service sees the document). Used for the Mundra stamp duty certificate, which
always arrives as a scan.

Runs in a child process with a time limit, one at a time per instance, so a heavy or broken
scan can't take the ERP's memory (1 GiB per instance) or hang a request; the model is loaded
only there. Text is found on a copy at most 960 px a side (peak ~300 MB, measured) and read
off the full-size render, which keeps the digits sharp.
Never raises: no OCR installed / unreadable / too slow -> None.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

MAX_PAGES = 2
TIMEOUT_S = 90
_ONE_AT_A_TIME = threading.Lock()


def ocr_text(path: str, timeout: int = TIMEOUT_S) -> Optional[str]:
    """The scan's text, one OCR'd line per line (first MAX_PAGES pages), or None."""
    try:
        with _ONE_AT_A_TIME:
            r = subprocess.run([sys.executable, "-m", "app.extraction.ocr", str(path)], capture_output=True,
                               text=True, timeout=timeout, cwd=str(Path(__file__).resolve().parents[2]))
    except (subprocess.TimeoutExpired, OSError) as e:
        log.warning("OCR failed for %s: %s", path, e)
        return None
    if r.returncode != 0:
        log.warning("OCR failed for %s: %s", path, (r.stderr or "")[-300:])
        return None
    return r.stdout or None


def _run(path: str) -> None:
    import numpy as np
    import pypdfium2 as pdfium
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR(det_model_path=None, det_limit_side_len=960, det_limit_type="max")
    pdf = pdfium.PdfDocument(path)
    for i in range(min(len(pdf), MAX_PAGES)):
        image = pdf[i].render(scale=2).to_pil().convert("RGB")
        result, _ = engine(np.array(image))
        for row in result or []:
            print(row[1])


if __name__ == "__main__":
    _run(sys.argv[1])
