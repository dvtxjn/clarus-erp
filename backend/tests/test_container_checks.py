import pytest

from app.liners import container_check_digit_ok


def _ship(tc, h, mbl, job):
    r = tc.post("/shipments", json={"mbl": mbl, "job": job, "client": "CC Test", "port": "INMUN1"}, headers=h)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_check_digit():
    assert container_check_digit_ok("MRKU5032093") and container_check_digit_ok("CSQU3054383")
    assert not container_check_digit_ok("MRKU5032094")


@pytest.mark.duplicates
def test_typed_containers_are_checked(client, admin_headers):
    a = _ship(client, admin_headers, "CCHK0000001", "C901")
    b = _ship(client, admin_headers, "CCHK0000002", "C902")
    add = lambda sid, no: client.post(f"/shipments/{sid}/containers", json={"container_no": no}, headers=admin_headers)
    assert add(a, "MRKU5032094").status_code == 422          # typo: check digit off
    first = add(a, "MRKU5032093")
    assert first.status_code == 201
    assert add(b, "MRKU5032093").status_code == 409          # already on an open shipment
    second = add(a, "CSQU3054383").json()
    assert client.get(f"/shipments/{a}", headers=admin_headers).json()["container"] == "2"
    # editing one into a number already on this shipment is refused
    r = client.patch(f"/shipments/{a}/containers/{second['id']}", json={"container_no": "MRKU5032093"},
                     headers=admin_headers)
    assert r.status_code == 409
    client.delete(f"/shipments/{a}/containers/{second['id']}", headers=admin_headers)
    assert client.get(f"/shipments/{a}", headers=admin_headers).json()["container"] == "1"
