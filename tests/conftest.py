"""Test fixtures.

Tests run against an in-memory SQLite database (never MySQL / production data):
the environment is forced *before* the application is imported, and the schema is
created from the models for each test. Row locking (``FOR UPDATE``) is a no-op on
SQLite - true concurrency behaviour must be verified against MySQL (see README).
"""
from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-test-secret-key-0123456789"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["TIMEZONE"] = "Asia/Kolkata"

from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402,F401
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import user_service  # noqa: E402
from app.websockets.manager import manager  # noqa: E402

PASSWORD = "Passw0rdTest"
HQ = (17.4486, 78.3908)          # restaurant location
NEAR = (17.4500, 78.3920)        # customer ~0.2 km away
FAR = (17.6000, 78.6000)         # far outside a 5 km radius


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    manager.capture = []
    yield
    manager.capture = None
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class World:
    """Helper that builds users / restaurants through the public API."""

    def __init__(self, client: TestClient):
        self.c = client
        self._n = 0

    def _next(self) -> int:
        self._n += 1
        return self._n

    def admin(self) -> dict:
        db = SessionLocal()
        try:
            email = f"admin{self._next()}@example.com"
            user_service.create_admin(db, "Admin", email, "9000000001", PASSWORD)
        finally:
            db.close()
        return self.login(email)

    def login(self, email: str) -> dict:
        r = self.c.post("/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        body = r.json()
        return {"id": body["user"]["id"], "token": body["access_token"], "h": auth(body["access_token"]), "email": email}

    def register(self, role: str, admin: dict | None = None, approve: bool = True, **extra) -> dict:
        n = self._next()
        email = f"{role.split()[0].lower()}{n}@example.com"
        payload = {"name": f"User {n}", "email": email, "phone": "9876543210", "password": PASSWORD, "role": role}
        payload.update(extra)
        r = self.c.post("/auth/register", json=payload)
        assert r.status_code == 201, r.text
        user_id = r.json()["id"]
        if approve and role != "Customer":
            assert admin is not None
            ra = self.c.put(f"/admin/users/{user_id}/approve", headers=admin["h"])
            assert ra.status_code == 200, ra.text
        return self.login(email)

    def customer(self) -> dict:
        return self.register("Customer")

    def owner(self, admin: dict) -> dict:
        return self.register("Restaurant Owner", admin)

    def partner(self, admin: dict, lat: float = HQ[0], lng: float = HQ[1], online: bool = True) -> dict:
        n = self._n + 1
        p = self.register("Delivery Partner", admin, vehicle_number=f"TS09AB{1000 + n}", vehicle_type="Bike")
        if online:
            self.go_online(p, lat, lng)
        return p

    def go_online(self, partner: dict, lat: float, lng: float) -> None:
        r = self.c.put("/partners/me/location", json={"latitude": lat, "longitude": lng}, headers=partner["h"])
        assert r.status_code == 200, r.text
        r = self.c.put("/partners/me/availability", json={"is_online": True}, headers=partner["h"])
        assert r.status_code == 200, r.text

    def restaurant(self, owner: dict, **overrides) -> dict:
        payload = {
            "name": "Spice Hub", "cuisine_type": "South Indian", "address": "Madhapur, Hyderabad",
            "latitude": HQ[0], "longitude": HQ[1], "opening_time": "00:00:00", "closing_time": "23:59:59",
            "delivery_radius_km": 5, "min_order_value": 100, "avg_preparation_minutes": 20,
        }
        payload.update(overrides)
        r = self.c.post("/restaurants", json=payload, headers=owner["h"])
        assert r.status_code == 201, r.text
        return r.json()

    def menu_item(self, owner: dict, restaurant_id: int, name="Masala Dosa", price=120, packaging=10, **kw) -> dict:
        rc = self.c.post(f"/restaurants/{restaurant_id}/categories", json={"name": kw.pop("category", "Mains")}, headers=owner["h"])
        if rc.status_code == 409:
            menu = self.c.get(f"/restaurants/{restaurant_id}/menu", headers=owner["h"]).json()
            cat_id = menu["categories"][0]["category_id"]
        else:
            assert rc.status_code == 201, rc.text
            cat_id = rc.json()["id"]
        payload = {"category_id": cat_id, "name": name, "price": price, "packaging_charge": packaging, "is_veg": True}
        payload.update(kw)
        r = self.c.post(f"/restaurants/{restaurant_id}/menu-items", json=payload, headers=owner["h"])
        assert r.status_code == 201, r.text
        return r.json()

    def address(self, customer: dict, lat=NEAR[0], lng=NEAR[1]) -> dict:
        r = self.c.post("/addresses", json={
            "label": "Home", "address_line": "Plot 1, Hitech City", "city": "Hyderabad",
            "pincode": "500081", "latitude": lat, "longitude": lng}, headers=customer["h"])
        assert r.status_code == 201, r.text
        return r.json()

    def add_to_cart(self, customer: dict, item_id: int, qty: int = 1):
        return self.c.post("/cart/items", json={"menu_item_id": item_id, "quantity": qty}, headers=customer["h"])

    def coupon(self, creator: dict, code="SAVE10", **kw) -> dict:
        now = datetime.now(timezone.utc)
        payload = {
            "code": code, "discount_type": "PERCENTAGE", "discount_value": 10, "max_discount": 50,
            "min_order_value": 100, "valid_from": (now - timedelta(days=1)).isoformat(),
            "valid_until": (now + timedelta(days=30)).isoformat(),
        }
        payload.update(kw)
        r = self.c.post("/coupons", json=payload, headers=creator["h"])
        assert r.status_code == 201, r.text
        return r.json()

    def place(self, customer: dict, address_id: int, method="COD", tip=0):
        return self.c.post("/orders", json={"address_id": address_id, "payment_method": method, "tip": tip},
                           headers=customer["h"])


@pytest.fixture()
def world(client):
    return World(client)


@pytest.fixture()
def setup(world):
    """Admin, owner, restaurant with one item (price 120, packaging 10), customer with an address."""
    admin = world.admin()
    owner = world.owner(admin)
    restaurant = world.restaurant(owner)
    item = world.menu_item(owner, restaurant["id"])
    customer = world.customer()
    address = world.address(customer)
    return {"w": world, "admin": admin, "owner": owner, "restaurant": restaurant, "item": item,
            "customer": customer, "address": address}


@pytest.fixture()
def placed_order(setup):
    """A placed COD order of 2 x Masala Dosa."""
    w, s = setup["w"], setup
    assert w.add_to_cart(s["customer"], s["item"]["id"], 2).status_code == 201
    r = w.place(s["customer"], s["address"]["id"])
    assert r.status_code == 201, r.text
    return r.json()


def complete_delivery(setup: dict, order: dict, partner: dict) -> dict:
    """Drive an already-placed order through accept -> assign -> pickup -> delivered."""
    c = setup["w"].c
    owner_h = setup["owner"]["h"]
    assert c.put(f"/orders/{order['id']}/accept", json={"preparation_minutes": 10}, headers=owner_h).status_code == 200
    offers = c.get("/partners/me/offers", headers=partner["h"]).json()["items"]
    assert offers, "partner should have received an offer"
    assert c.put(f"/offers/{offers[0]['id']}/accept", headers=partner["h"]).status_code == 200
    assert c.put(f"/orders/{order['id']}/preparing", headers=owner_h).status_code == 200
    assert c.put(f"/orders/{order['id']}/ready", headers=owner_h).status_code == 200
    assert c.put(f"/orders/{order['id']}/pickup", headers=partner["h"]).status_code == 200
    assert c.put(f"/orders/{order['id']}/out-for-delivery", headers=partner["h"]).status_code == 200
    r = c.put(f"/orders/{order['id']}/deliver", json={"otp": order["delivery_otp"]}, headers=partner["h"])
    assert r.status_code == 200, r.text
    return r.json()
