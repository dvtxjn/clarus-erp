"""The restore test only ever targets the scratch database."""
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from restore_check import SCRATCH, scratch_url  # noqa: E402


def test_scratch_url_swaps_only_the_database():
    live = "postgresql+psycopg2://erp:p%40ss@/erp_db?host=/cloudsql/p:r:i"
    url = scratch_url(live)
    assert "/erp_restore_check?" in url and "erp_db" not in url
    assert "host=/cloudsql/p:r:i" in unquote(url) and "p%40ss" in url


def test_refuses_the_scratch_url_itself():
    with pytest.raises(SystemExit):
        scratch_url(f"postgresql://erp@localhost/{SCRATCH}")
