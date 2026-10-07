"""Client, 2026-09-29: the admin controls every password; users can't change their own,
"Forgot password" only flags the account for the admin."""


def _login(client, email, pw):
    return client.post("/auth/login", data={"username": email, "password": pw})


def test_admin_manages_logins_users_cant_change_passwords(client, admin_headers):
    h = admin_headers
    r = client.post("/auth/users", json={"email": "Staff.One@Example.com", "password": "first-password-1",
                                         "full_name": "Staff One", "role": "import_manager"}, headers=h)
    assert r.status_code == 201 and r.json()["email"] == "staff.one@example.com"
    uid = r.json()["id"]
    assert client.post("/auth/users", json={"email": "x@example.com", "password": "short", "full_name": "X"},
                       headers=h).status_code == 422  # 12 characters minimum
    tok = _login(client, "STAFF.ONE@example.com", "first-password-1").json()["access_token"]  # any capitals
    u = {"Authorization": f"Bearer {tok}"}
    assert client.post("/auth/change-password", json={"current_password": "first-password-1",
                                                      "new_password": "my-own-password"}, headers=u).status_code == 403
    assert client.get("/auth/users", headers=u).status_code == 403  # not an admin

    # forgot password: flags the account (and says nothing about unknown emails)
    assert client.post("/auth/forgot-password", json={"email": "staff.one@example.com"}).status_code == 204
    assert client.post("/auth/forgot-password", json={"email": "nobody@example.com"}).status_code == 204
    row = next(x for x in client.get("/auth/users", headers=h).json() if x["id"] == uid)
    assert row["password_reset_requested_at"] and row["last_login_at"]

    # the admin sets a new one: the request clears, the old password stops working
    r = client.post(f"/auth/users/{uid}/password", json={"new_password": "second-password-2"}, headers=h)
    assert r.status_code == 200 and r.json()["password_reset_requested_at"] is None
    assert _login(client, "staff.one@example.com", "first-password-1").status_code == 401
    assert _login(client, "staff.one@example.com", "second-password-2").status_code == 200

    # switched off: can't log in
    client.patch(f"/auth/users/{uid}", json={"is_active": False}, headers=h)
    assert _login(client, "staff.one@example.com", "second-password-2").status_code == 403


def test_admin_cannot_lock_themselves_out(client, admin_headers):
    me = client.get("/auth/me", headers=admin_headers).json()
    assert client.patch(f"/auth/users/{me['id']}", json={"is_active": False}, headers=admin_headers).status_code == 400
    assert client.patch(f"/auth/users/{me['id']}", json={"role": "import_manager"}, headers=admin_headers).status_code == 400


def test_view_only_login_reads_but_cannot_change(client, admin_headers):
    """Client, 2026-10-07: the QA bot may look at data, never change it — the server refuses every write."""
    h = admin_headers
    r = client.post("/auth/users", json={"email": "qa-bot", "password": "qa-bot-password-1",
                                         "full_name": "QA bot", "role": "admin"}, headers=h)
    uid = r.json()["id"]
    r = client.patch(f"/auth/users/{uid}", json={"read_only": True}, headers=h)
    assert r.status_code == 200 and r.json()["read_only"] is True
    bot = {"Authorization": f"Bearer {_login(client, 'qa-bot', 'qa-bot-password-1').json()['access_token']}"}

    assert client.get("/shipments", headers=bot).status_code == 200
    assert client.get("/auth/users", headers=bot).status_code == 200  # an admin that can look
    r = client.post("/shipments", json={"job": "QA1", "mbl": "QA-MBL-1"}, headers=bot)
    assert r.status_code == 403 and "view-only" in r.json()["detail"]
    assert client.patch(f"/auth/users/{uid}", json={"read_only": False}, headers=bot).status_code == 403

    # switched back: it can write again
    client.patch(f"/auth/users/{uid}", json={"read_only": False}, headers=h)
    assert client.patch(f"/auth/users/{uid}", json={"full_name": "QA bot 2"}, headers=bot).status_code == 200
