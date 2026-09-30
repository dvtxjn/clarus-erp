"""ICD public enquiry: a BL found at the ICD whose containers aren't listed yet (ICEGATE answers 400)."""
import httpx

from app.igm import icd


def test_containers_not_listed_yet_still_returns_the_bl():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("publicblstatus-action"):
            return httpx.Response(200, json=[{"igmRTN": "1212400", "igmDT": "21 SEP 2026", "portREP": "INMUN1", "lineNo": "5"}])
        return httpx.Response(400, json={"httpError": "BAD_REQUEST", "message": "No Record Found !!"})

    got = icd.fetch("274089878", httpx.Client(transport=httpx.MockTransport(handler)))
    assert got["found"] and got["bls"][0]["gateway_port"] == "INMUN1" and got["containers"] == []
