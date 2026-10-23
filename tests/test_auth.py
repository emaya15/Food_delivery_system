"""Level 2 / 13: registration, login, JWT and role checks."""
from datetime import timedelta

from app.auth.security import create_access_token
from tests.conftest import PASSWORD, auth


def reg(client, **kw):
    payload = {"name": "Asha", "email": "asha@example.com", "phone": "9876543210", "password": PASSWORD, "role": "Customer"}
    payload.update(kw)
    return client.post("/auth/register", json=payload)


def test_register_and_login_customer(client):
    r = reg(client)
    assert r.status_code == 201
    body = r.json()
    assert "password" not in str(body) and "password_hash" not in body
    assert body["is_approved"] is True
    login = client.post("/auth/login", json={"email": "ASHA@example.com", "password": PASSWORD})
    assert login.status_code == 200
    assert login.json()["expires_in"] == 30 * 60
    me = client.get("/auth/me", headers=auth(login.json()["access_token"]))
    assert me.status_code == 200 and me.json()["email"] == "asha@example.com"


def test_passwords_are_bcrypt_hashed(client, db):
    from app.models.user import User

    reg(client)
    assert db.query(User).one().password_hash.startswith("$2")


def test_admin_cannot_register_publicly(client):
    assert reg(client, role="Admin").status_code == 403


def test_duplicate_email_conflict(client):
    assert reg(client).status_code == 201
    assert reg(client).status_code == 409


def test_validation_errors_return_422(client):
    assert reg(client, phone="12345").status_code == 422
    assert reg(client, password="short").status_code == 422
    assert reg(client, email="not-an-email").status_code == 422


def test_wrong_password_and_unknown_user_are_401(client):
    reg(client)
    assert client.post("/auth/login", json={"email": "asha@example.com", "password": "Wrong1234"}).status_code == 401
    assert client.post("/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}).status_code == 401


def test_inactive_user_cannot_login(client, db):
    from app.models.user import User

    reg(client)
    user = db.query(User).one()
    user.is_active = False
    db.commit()
    assert client.post("/auth/login", json={"email": "asha@example.com", "password": PASSWORD}).status_code == 403


def test_missing_invalid_and_expired_tokens_are_401(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers=auth("garbage")).status_code == 401
    reg(client)
    expired = create_access_token(1, expires_delta=timedelta(seconds=-5))
    r = client.get("/auth/me", headers=auth(expired))
    assert r.status_code == 401 and "expired" in r.json()["error"]["message"].lower()


def test_delivery_partner_requires_vehicle_and_unique_vehicle(client):
    base = dict(role="Delivery Partner")
    assert reg(client, **base).status_code == 422
    ok = reg(client, vehicle_number="TS09AB1234", vehicle_type="Bike", **base)
    assert ok.status_code == 201
    dup = reg(client, email="other@example.com", vehicle_number="ts09ab1234", vehicle_type="Bike", **base)
    assert dup.status_code == 409


def test_admin_approval_flow_and_rbac(world, client):
    admin = world.admin()
    owner = world.register("Restaurant Owner", approve=False)
    payload = {"name": "Roma Pizza", "cuisine_type": "Pizza", "address": "Somewhere", "latitude": 17.4, "longitude": 78.4,
               "opening_time": "09:00:00", "closing_time": "22:00:00"}
    # unapproved owner -> 403
    assert client.post("/restaurants", json=payload, headers=owner["h"]).status_code == 403
    # non-admin cannot approve
    uid = owner["id"]
    assert client.put(f"/admin/users/{uid}/approve", headers=owner["h"]).status_code == 403
    assert client.put(f"/admin/users/{uid}/approve", headers=admin["h"]).status_code == 200
    assert client.post("/restaurants", json=payload, headers=owner["h"]).status_code == 201


def test_cannot_approve_customer_or_missing_user(world, client):
    admin = world.admin()
    cust = world.customer()
    assert client.put(f"/admin/users/{cust['id']}/approve", headers=admin["h"]).status_code == 400
    assert client.put("/admin/users/9999/approve", headers=admin["h"]).status_code == 404


def test_unapproved_partner_cannot_go_online(world, client):
    p = world.register("Delivery Partner", approve=False, vehicle_number="TS09AB9999", vehicle_type="Bike")
    r = client.put("/partners/me/availability", json={"is_online": True}, headers=p["h"])
    assert r.status_code == 403
