"""Levels 7, 8: order placement, billing, cancellation, restaurant transitions."""
from decimal import Decimal as D

import pytest

from app.models.coupon import Coupon, CouponUsage
from app.models.order import Order
from app.services import billing


def money(x) -> D:
    return D(str(x)).quantize(D("0.01"))


def test_place_order_billing_matches_rules(placed_order):
    o = placed_order
    assert o["status"] == "Placed" and o["payment_status"] == "Pending"
    assert o["order_number"].startswith("ORD-") and o["order_number"].endswith("-0001")
    assert len(o["delivery_otp"]) == 4 and o["delivery_otp"].isdigit()
    assert money(o["item_total"]) == D("240.00")
    assert money(o["packaging_charges"]) == D("20.00")
    assert money(o["platform_fee"]) == D("5.00")
    assert money(o["gst"]) == D("12.00")                 # 5% of 240
    expected_fee = D("30.00") if o["surge_applied"] else D("20.00")   # 0.2 km -> within first 3 km
    assert money(o["delivery_fee"]) == expected_fee
    assert money(o["grand_total"]) == D("240") + D("20") + expected_fee + D("5") + D("12")
    assert o["status_history"][0]["to_status"] == "Placed"


def test_order_numbers_are_sequential_and_unique(setup):
    w, s = setup["w"], setup
    numbers = []
    for _ in range(3):
        w.add_to_cart(s["customer"], s["item"]["id"], 1)
        numbers.append(w.place(s["customer"], s["address"]["id"]).json()["order_number"])
    assert [n[-4:] for n in numbers] == ["0001", "0002", "0003"] and len(set(numbers)) == 3


def test_cart_cleared_after_order(placed_order, setup):
    cart = setup["w"].c.get("/cart", headers=setup["customer"]["h"]).json()
    assert cart["items"] == [] and cart["coupon_code"] is None


def test_online_payment_is_paid_and_tip_included(setup):
    w, s = setup["w"], setup
    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    o = w.place(s["customer"], s["address"]["id"], method="ONLINE", tip=15).json()
    assert o["payment_status"] == "Paid" and money(o["tip"]) == D("15.00")
    assert w.place(s["customer"], s["address"]["id"], tip=-1).status_code in (400, 422)


def test_validation_failures_do_not_create_orders(setup, db):
    w, s = setup["w"], setup
    assert w.place(s["customer"], s["address"]["id"]).status_code == 400            # empty cart
    w.add_to_cart(s["customer"], s["item"]["id"], 1)                                # 120 >= min 100
    far = w.address(s["customer"], lat=17.6, lng=78.6)
    assert w.place(s["customer"], far["id"]).status_code == 400                     # outside radius
    assert w.place(s["customer"], 9999).status_code == 404
    other = w.customer()
    foreign = w.address(other)
    assert w.place(s["customer"], foreign["id"]).status_code == 404                 # someone else's address
    assert db.query(Order).count() == 0


def test_minimum_order_value_enforced(setup):
    w, s = setup["w"], setup
    cheap = w.menu_item(s["owner"], s["restaurant"]["id"], name="Tea", price=20, packaging=0)
    w.add_to_cart(s["customer"], cheap["id"], 1)
    r = w.place(s["customer"], s["address"]["id"])
    assert r.status_code == 400 and "Minimum order value" in r.json()["error"]["message"]


def test_closed_restaurant_rejects_orders(setup):
    w, s = setup["w"], setup
    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    w.c.put(f"/restaurants/{s['restaurant']['id']}/open-status", json={"is_temporarily_closed": True}, headers=s["owner"]["h"])
    assert w.place(s["customer"], s["address"]["id"]).status_code == 400


def test_transaction_rolls_back_coupon_usage_when_order_fails(setup, db, monkeypatch):
    """If anything fails after the coupon is consumed, nothing is persisted."""
    w, s = setup["w"], setup
    w.coupon(s["admin"], code="ONCE", discount_type="FLAT", discount_value=30, max_discount=None, usage_limit_total=1)
    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    w.c.post("/cart/apply-coupon", json={"code": "ONCE"}, headers=s["customer"]["h"])

    from app.services import order_service

    def boom(*a, **k):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(order_service, "queue_event", boom)
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as c2:
        r = c2.post("/orders", json={"address_id": s["address"]["id"], "payment_method": "COD"}, headers=s["customer"]["h"])
    assert r.status_code == 500
    db.expire_all()
    assert db.query(Order).count() == 0
    assert db.query(CouponUsage).count() == 0
    assert db.query(Coupon).filter_by(code="ONCE").one().used_count == 0
    # the cart (and coupon) are untouched, so the customer can retry
    monkeypatch.undo()
    assert w.c.get("/cart", headers=s["customer"]["h"]).json()["coupon_code"] == "ONCE"
    assert w.place(s["customer"], s["address"]["id"]).status_code == 201


def test_coupon_usage_limit_and_release_on_cancel(setup, db):
    w, s, c = setup["w"], setup, setup["w"].c
    w.coupon(s["admin"], code="ONCE", discount_type="FLAT", discount_value=30, max_discount=None, usage_limit_total=1)
    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    c.post("/cart/apply-coupon", json={"code": "ONCE"}, headers=s["customer"]["h"])
    first = w.place(s["customer"], s["address"]["id"]).json()
    assert money(first["discount"]) == D("30.00") and first["coupon_code"] == "ONCE"
    db.expire_all()
    assert db.query(Coupon).filter_by(code="ONCE").one().used_count == 1

    other = w.customer()
    addr = w.address(other)
    w.add_to_cart(other, s["item"]["id"], 1)
    assert c.post("/cart/apply-coupon", json={"code": "ONCE"}, headers=other["h"]).status_code == 400  # exhausted

    assert c.put(f"/orders/{first['id']}/cancel", headers=s["customer"]["h"]).status_code == 200
    db.expire_all()
    assert db.query(Coupon).filter_by(code="ONCE").one().used_count == 0
    assert c.post("/cart/apply-coupon", json={"code": "ONCE"}, headers=other["h"]).status_code == 200
    assert w.place(other, addr["id"]).status_code == 201


def test_per_user_limit_and_first_order_only(setup):
    w, s, c = setup["w"], setup, setup["w"].c
    w.coupon(s["admin"], code="PERUSER", discount_type="FLAT", discount_value=10, max_discount=None, usage_limit_per_user=1)
    w.coupon(s["admin"], code="FIRST", discount_type="FLAT", discount_value=10, max_discount=None, first_order_only=True)
    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    c.post("/cart/apply-coupon", json={"code": "PERUSER"}, headers=s["customer"]["h"])
    assert w.place(s["customer"], s["address"]["id"]).status_code == 201
    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    assert c.post("/cart/apply-coupon", json={"code": "PERUSER"}, headers=s["customer"]["h"]).status_code == 400
    assert c.post("/cart/apply-coupon", json={"code": "FIRST"}, headers=s["customer"]["h"]).status_code == 400


def test_cancellation_only_while_placed_and_refund(setup):
    w, s, c = setup["w"], setup, setup["w"].c
    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    paid = w.place(s["customer"], s["address"]["id"], method="ONLINE").json()
    r = c.put(f"/orders/{paid['id']}/cancel", json={"reason": "changed mind"}, headers=s["customer"]["h"])
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "Cancelled" and body["payment_status"] == "Refunded"
    assert body["status_history"][-1]["to_status"] == "Cancelled"
    assert c.put(f"/orders/{paid['id']}/cancel", headers=s["customer"]["h"]).status_code == 400  # already cancelled

    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    o2 = w.place(s["customer"], s["address"]["id"]).json()
    c.put(f"/orders/{o2['id']}/accept", json={"preparation_minutes": 15}, headers=s["owner"]["h"])
    assert c.put(f"/orders/{o2['id']}/cancel", headers=s["customer"]["h"]).status_code == 400  # past 'Placed'


def test_only_owner_customer_can_cancel_own_order(placed_order, setup):
    stranger = setup["w"].customer()
    assert setup["w"].c.put(f"/orders/{placed_order['id']}/cancel", headers=stranger["h"]).status_code == 404


def test_otp_visible_only_to_customer(placed_order, setup):
    c = setup["w"].c
    assert c.get(f"/orders/{placed_order['id']}", headers=setup["customer"]["h"]).json()["delivery_otp"] == placed_order["delivery_otp"]
    for who in ("owner", "admin"):
        body = c.get(f"/orders/{placed_order['id']}", headers=setup[who]["h"]).json()
        assert body["delivery_otp"] is None
    listed = c.get("/restaurants/me/orders", headers=setup["owner"]["h"]).json()["items"]
    assert listed[0]["delivery_otp"] is None


def test_users_cannot_read_other_customers_orders(placed_order, setup):
    stranger = setup["w"].customer()
    assert setup["w"].c.get(f"/orders/{placed_order['id']}", headers=stranger["h"]).status_code == 404
    assert setup["w"].c.get("/orders", headers=stranger["h"]).json()["total"] == 0


def test_order_list_filters(placed_order, setup):
    c, h = setup["w"].c, setup["customer"]["h"]
    assert c.get("/orders?status=Placed", headers=h).json()["total"] == 1
    assert c.get("/orders?status=Delivered", headers=h).json()["total"] == 0
    assert c.get(f"/orders?restaurant_id={setup['restaurant']['id']}", headers=h).json()["total"] == 1
    assert c.get("/orders?restaurant_id=999", headers=h).json()["total"] == 0
    assert c.get("/orders?from_date=2000-01-01&to_date=2100-01-01", headers=h).json()["total"] == 1
    assert c.get("/orders?from_date=2100-01-01&to_date=2000-01-01", headers=h).status_code == 400
    assert c.get("/orders?status=Bogus", headers=h).status_code == 422


def test_reorder_skips_unavailable_and_does_not_reapply_coupon(setup):
    w, s, c = setup["w"], setup, setup["w"].c
    other_item = w.menu_item(s["owner"], s["restaurant"]["id"], name="Vada", price=50, packaging=0)
    w.coupon(s["admin"], code="FLAT10", discount_type="FLAT", discount_value=10, max_discount=None)
    w.add_to_cart(s["customer"], s["item"]["id"], 2)
    w.add_to_cart(s["customer"], other_item["id"], 1)
    c.post("/cart/apply-coupon", json={"code": "FLAT10"}, headers=s["customer"]["h"])
    first = w.place(s["customer"], s["address"]["id"]).json()
    c.put(f"/menu-items/{other_item['id']}/availability", json={"is_available": False}, headers=s["owner"]["h"])
    r = c.post(f"/orders/{first['id']}/reorder", headers=s["customer"]["h"])
    assert r.status_code == 201
    body = r.json()
    assert body["added_items"] == ["Masala Dosa"] and body["skipped_items"] == ["Vada"]
    assert body["cart"]["coupon_code"] is None and body["cart"]["items"][0]["quantity"] == 2


def test_restaurant_transitions_and_history(placed_order, setup):
    c, o = setup["w"].c, placed_order
    h = setup["owner"]["h"]
    assert c.put(f"/orders/{o['id']}/preparing", headers=h).status_code == 400   # must be accepted first
    assert c.put(f"/orders/{o['id']}/accept", json={}, headers=h).status_code == 422  # prep time required
    ok = c.put(f"/orders/{o['id']}/accept", json={"preparation_minutes": 25}, headers=h)
    assert ok.status_code == 200 and ok.json()["status"] == "Accepted" and ok.json()["preparation_minutes"] == 25
    assert c.put(f"/orders/{o['id']}/ready", headers=h).status_code == 400      # skipping Preparing
    assert c.put(f"/orders/{o['id']}/preparing", headers=h).json()["status"] == "Preparing"
    ready = c.put(f"/orders/{o['id']}/ready", headers=h).json()
    assert ready["status"] == "Ready for Pickup"
    assert [x["to_status"] for x in ready["status_history"]] == ["Placed", "Accepted", "Preparing", "Ready for Pickup"]
    assert c.put(f"/orders/{o['id']}/reject", json={"reason": "late"}, headers=h).status_code == 400  # too late


def test_reject_requires_reason_and_refunds(setup):
    w, s, c = setup["w"], setup, setup["w"].c
    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    o = w.place(s["customer"], s["address"]["id"], method="ONLINE").json()
    assert c.put(f"/orders/{o['id']}/reject", json={}, headers=s["owner"]["h"]).status_code == 422
    r = c.put(f"/orders/{o['id']}/reject", json={"reason": "Out of stock"}, headers=s["owner"]["h"])
    assert r.status_code == 200
    assert r.json()["status"] == "Rejected" and r.json()["payment_status"] == "Refunded"
    assert r.json()["rejection_reason"] == "Out of stock"


def test_only_restaurants_owner_can_manage_order(placed_order, setup):
    w, c = setup["w"], setup["w"].c
    other = w.owner(setup["admin"])
    assert c.put(f"/orders/{placed_order['id']}/accept", json={"preparation_minutes": 10}, headers=other["h"]).status_code == 403
    assert c.put(f"/orders/{placed_order['id']}/reject", json={"reason": "not your order"}, headers=other["h"]).status_code == 403
    assert c.get("/restaurants/me/orders", headers=other["h"]).json()["total"] == 0
    assert c.put(f"/orders/{placed_order['id']}/accept", json={"preparation_minutes": 10}, headers=setup["customer"]["h"]).status_code == 403


def test_scheduled_order_must_be_later_today(setup):
    from datetime import datetime, timedelta, timezone

    w, s = setup["w"], setup
    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    soon = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    r = w.c.post("/orders", json={"address_id": s["address"]["id"], "payment_method": "COD", "scheduled_for": soon},
                 headers=s["customer"]["h"])
    assert r.status_code == 400
    nextweek = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    r = w.c.post("/orders", json={"address_id": s["address"]["id"], "payment_method": "COD", "scheduled_for": nextweek},
                 headers=s["customer"]["h"])
    assert r.status_code == 400
