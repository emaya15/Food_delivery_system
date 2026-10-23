"""Levels 5, 6: cart rules and coupon rules."""
from datetime import datetime, timedelta, timezone

from app.utils.constants import CART_CONFLICT_MESSAGE


def test_add_same_item_increases_quantity(setup):
    w, s = setup["w"], setup
    w.add_to_cart(s["customer"], s["item"]["id"], 2)
    r = w.add_to_cart(s["customer"], s["item"]["id"], 3)
    body = r.json()
    assert len(body["items"]) == 1 and body["items"][0]["quantity"] == 5
    assert body["items"][0]["line_total"] == 600 and body["item_total"] == 600


def test_quantity_limits(setup):
    w, s = setup["w"], setup
    assert w.add_to_cart(s["customer"], s["item"]["id"], 0).status_code == 422
    assert w.add_to_cart(s["customer"], s["item"]["id"], 11).status_code == 422
    assert w.add_to_cart(s["customer"], s["item"]["id"], 8).status_code == 201
    assert w.add_to_cart(s["customer"], s["item"]["id"], 5).status_code == 400  # would reach 13


def test_update_quantity_and_remove(setup):
    w, s, c = setup["w"], setup, setup["w"].c
    cart = w.add_to_cart(s["customer"], s["item"]["id"], 1).json()
    line = cart["items"][0]["id"]
    assert c.put(f"/cart/items/{line}", json={"quantity": 11}, headers=s["customer"]["h"]).status_code == 422
    assert c.put(f"/cart/items/{line}", json={"quantity": 4}, headers=s["customer"]["h"]).json()["item_total"] == 480
    emptied = c.delete(f"/cart/items/{line}", headers=s["customer"]["h"]).json()
    assert emptied["items"] == [] and emptied["restaurant_id"] is None


def test_other_restaurant_returns_409_with_required_message(setup):
    w, s = setup["w"], setup
    owner2 = w.owner(s["admin"])
    r2 = w.restaurant(owner2, name="Other")
    item2 = w.menu_item(owner2, r2["id"], name="Pizza", price=200)
    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    r = w.add_to_cart(s["customer"], item2["id"], 1)
    assert r.status_code == 409
    assert r.json()["error"]["message"] == CART_CONFLICT_MESSAGE == "Your cart has items from another restaurant. Clear the cart to continue"
    # after clearing, the other restaurant is accepted
    assert w.c.delete("/cart", headers=s["customer"]["h"]).status_code == 200
    assert w.add_to_cart(s["customer"], item2["id"], 1).status_code == 201


def test_unavailable_item_rejected(setup):
    w, s = setup["w"], setup
    w.c.put(f"/menu-items/{s['item']['id']}/availability", json={"is_available": False}, headers=s["owner"]["h"])
    assert w.add_to_cart(s["customer"], s["item"]["id"], 1).status_code == 400


def test_only_customers_have_carts(setup):
    assert setup["w"].c.get("/cart", headers=setup["owner"]["h"]).status_code == 403


def test_percentage_coupon_with_cap_and_case_insensitive(setup):
    w, s, c = setup["w"], setup, setup["w"].c
    w.coupon(s["admin"], code="SAVE10")
    w.add_to_cart(s["customer"], s["item"]["id"], 10)  # 1200 -> 10% = 120, capped at 50
    r = c.post("/cart/apply-coupon", json={"code": "save10"}, headers=s["customer"]["h"])
    assert r.status_code == 200
    body = r.json()
    assert body["coupon_code"] == "SAVE10" and body["discount"] == 50 and body["total_after_discount"] == 1150


def test_flat_coupon_and_removal(setup):
    w, s, c = setup["w"], setup, setup["w"].c
    w.coupon(s["admin"], code="FLAT30", discount_type="FLAT", discount_value=30, max_discount=None)
    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    body = c.post("/cart/apply-coupon", json={"code": "FLAT30"}, headers=s["customer"]["h"]).json()
    assert body["discount"] == 30 and body["total_after_discount"] == 90
    assert c.delete("/cart/coupon", headers=s["customer"]["h"]).json()["discount"] == 0


def test_clearing_cart_clears_coupon(setup):
    w, s, c = setup["w"], setup, setup["w"].c
    w.coupon(s["admin"], code="FLAT30", discount_type="FLAT", discount_value=30, max_discount=None)
    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    c.post("/cart/apply-coupon", json={"code": "FLAT30"}, headers=s["customer"]["h"])
    cleared = c.delete("/cart", headers=s["customer"]["h"]).json()
    assert cleared["coupon_code"] is None
    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    assert c.get("/cart", headers=s["customer"]["h"]).json()["coupon_code"] is None


def test_invalid_coupon_cases_return_400(setup):
    w, s, c = setup["w"], setup, setup["w"].c
    now = datetime.now(timezone.utc)
    w.coupon(s["admin"], code="BIGMIN", min_order_value=5000)
    w.coupon(s["admin"], code="OLD", valid_from=(now - timedelta(days=10)).isoformat(), valid_until=(now - timedelta(days=1)).isoformat())
    w.coupon(s["admin"], code="FUTURE", valid_from=(now + timedelta(days=1)).isoformat(), valid_until=(now + timedelta(days=5)).isoformat())
    off = w.coupon(s["admin"], code="OFF")
    c.put(f"/coupons/{off['id']}/deactivate", headers=s["admin"]["h"])
    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    for code in ("NOPE", "BIGMIN", "OLD", "FUTURE", "OFF"):
        r = c.post("/cart/apply-coupon", json={"code": code}, headers=s["customer"]["h"])
        assert r.status_code == 400, (code, r.text)
        assert r.json()["error"]["message"]


def test_restaurant_specific_coupon_only_for_that_restaurant(setup):
    w, s, c = setup["w"], setup, setup["w"].c
    owner2 = w.owner(s["admin"])
    r2 = w.restaurant(owner2, name="Other")
    item2 = w.menu_item(owner2, r2["id"], name="Pizza", price=200)
    w.coupon(owner2, code="OTHER10", restaurant_id=r2["id"])
    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    assert c.post("/cart/apply-coupon", json={"code": "OTHER10"}, headers=s["customer"]["h"]).status_code == 400


def test_owner_coupon_permissions(setup):
    w, s, c = setup["w"], setup, setup["w"].c
    now = datetime.now(timezone.utc)
    body = {"code": "OWN1", "discount_type": "FLAT", "discount_value": 10, "valid_from": now.isoformat(),
            "valid_until": (now + timedelta(days=2)).isoformat()}
    assert c.post("/coupons", json=body, headers=s["owner"]["h"]).status_code == 403   # platform-wide: admin only
    other = w.owner(s["admin"])
    r = c.post("/coupons", json={**body, "restaurant_id": s["restaurant"]["id"]}, headers=other["h"])
    assert r.status_code == 403                                                        # not their restaurant
    assert c.post("/coupons", json={**body, "restaurant_id": s["restaurant"]["id"]}, headers=s["owner"]["h"]).status_code == 201
    assert c.post("/coupons", json={**body, "code": "own1", "restaurant_id": s["restaurant"]["id"]}, headers=s["owner"]["h"]).status_code == 409
    assert c.post("/coupons", json=body, headers=s["customer"]["h"]).status_code == 403


def test_coupon_validation_rules(setup):
    c, s = setup["w"].c, setup
    now = datetime.now(timezone.utc)
    good = {"code": "VAL1", "discount_type": "PERCENTAGE", "discount_value": 10, "valid_from": now.isoformat(),
            "valid_until": (now + timedelta(days=2)).isoformat()}
    assert c.post("/coupons", json={**good, "discount_value": 150}, headers=s["admin"]["h"]).status_code == 422
    assert c.post("/coupons", json={**good, "code": "VAL0", "discount_value": 0.5}, headers=s["admin"]["h"]).status_code == 422
    assert c.post("/coupons", json={**good, "code": "VAL2", "discount_value": -5}, headers=s["admin"]["h"]).status_code == 422
    assert c.post("/coupons", json={**good, "code": "VAL3", "valid_until": (now - timedelta(days=1)).isoformat()},
                  headers=s["admin"]["h"]).status_code == 422


def test_coupon_list_filters_and_available_preview(setup):
    w, s, c = setup["w"], setup, setup["w"].c
    w.coupon(s["admin"], code="PCT", discount_value=10)
    w.coupon(s["admin"], code="FLT", discount_type="FLAT", discount_value=20, max_discount=None)
    flats = c.get("/coupons?discount_type=FLAT", headers=s["admin"]["h"]).json()
    assert [x["code"] for x in flats["items"]] == ["FLT"]
    w.add_to_cart(s["customer"], s["item"]["id"], 2)
    avail = c.get("/coupons/available", headers=s["customer"]["h"]).json()["items"]
    by_code = {a["code"]: a for a in avail}
    assert by_code["PCT"]["eligible"] is True and by_code["PCT"]["discount"] == 24
    assert by_code["FLT"]["discount"] == 20
