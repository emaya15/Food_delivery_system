"""Levels 12, 15: ratings, reports and role-based report access."""
from decimal import Decimal as D

from tests.conftest import HQ, complete_delivery


def delivered(setup, qty=2, coupon=None):
    w, s = setup["w"], setup
    p = s.get("partner") or w.partner(s["admin"], HQ[0] + 0.001, HQ[1])
    s["partner"] = p
    w.add_to_cart(s["customer"], s["item"]["id"], qty)
    if coupon:
        w.c.post("/cart/apply-coupon", json={"code": coupon}, headers=s["customer"]["h"])
    order = w.place(s["customer"], s["address"]["id"]).json()
    return complete_delivery(s, order, p) | {"delivery_otp": order["delivery_otp"]}


def test_rating_rules(setup, placed_order):
    w, s, c = setup["w"], setup, setup["w"].c
    # not delivered yet
    assert c.post(f"/orders/{placed_order['id']}/rating", json={"restaurant_rating": 5}, headers=s["customer"]["h"]).status_code == 400
    p = w.partner(s["admin"], HQ[0] + 0.001, HQ[1])
    complete_delivery(s, placed_order, p)
    url = f"/orders/{placed_order['id']}/rating"
    stranger = w.customer()
    assert c.post(url, json={"restaurant_rating": 5}, headers=stranger["h"]).status_code == 404
    assert c.post(url, json={"restaurant_rating": 6}, headers=s["customer"]["h"]).status_code == 422
    assert c.post(url, json={"restaurant_rating": 0}, headers=s["customer"]["h"]).status_code == 422
    assert c.post(url, json={"restaurant_rating": 4, "partner_rating": 9}, headers=s["customer"]["h"]).status_code == 422
    ok = c.post(url, json={"restaurant_rating": 4, "partner_rating": 5, "comment": "Great"}, headers=s["customer"]["h"])
    assert ok.status_code == 201 and ok.json()["partner_id"] == p["id"]
    assert c.post(url, json={"restaurant_rating": 5}, headers=s["customer"]["h"]).status_code == 409   # one per order
    assert c.post(url, json={"restaurant_rating": 5}, headers=s["owner"]["h"]).status_code == 403


def test_restaurant_average_updates_automatically(setup):
    w, s, c = setup["w"], setup, setup["w"].c
    first = delivered(setup)
    second = delivered(setup)
    c.post(f"/orders/{first['id']}/rating", json={"restaurant_rating": 5}, headers=s["customer"]["h"])
    r = c.get(f"/restaurants/{s['restaurant']['id']}", headers=s["customer"]["h"]).json()
    assert D(str(r["average_rating"])) == D("5.00") and r["rating_count"] == 1
    c.post(f"/orders/{second['id']}/rating", json={"restaurant_rating": 2, "comment": "cold"}, headers=s["customer"]["h"])
    r = c.get(f"/restaurants/{s['restaurant']['id']}", headers=s["customer"]["h"]).json()
    assert D(str(r["average_rating"])) == D("3.50") and r["rating_count"] == 2
    listing = c.get(f"/restaurants/{s['restaurant']['id']}/ratings?limit=1", headers=s["customer"]["h"]).json()
    assert listing["total"] == 2 and len(listing["items"]) == 1 and D(str(listing["average_rating"])) == D("3.50")
    assert c.get("/restaurants/9999/ratings", headers=s["customer"]["h"]).status_code == 404


def test_cannot_rate_a_cancelled_order(setup):
    w, s, c = setup["w"], setup, setup["w"].c
    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    order = w.place(s["customer"], s["address"]["id"]).json()
    c.put(f"/orders/{order['id']}/cancel", headers=s["customer"]["h"])
    assert c.post(f"/orders/{order['id']}/rating", json={"restaurant_rating": 5}, headers=s["customer"]["h"]).status_code == 400


def test_dashboard_admin_only_and_counts(setup):
    w, s, c = setup["w"], setup, setup["w"].c
    w.coupon(s["admin"], code="FLAT20", discount_type="FLAT", discount_value=20, max_discount=None)
    delivered(setup, coupon="FLAT20")
    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    cancelled = w.place(s["customer"], s["address"]["id"]).json()
    c.put(f"/orders/{cancelled['id']}/cancel", headers=s["customer"]["h"])
    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    rejected = w.place(s["customer"], s["address"]["id"]).json()
    c.put(f"/orders/{rejected['id']}/reject", json={"reason": "closed"}, headers=s["owner"]["h"])

    for who in ("customer", "owner"):
        assert c.get("/reports/admin-dashboard", headers=s[who]["h"]).status_code == 403
    assert c.get("/reports/admin-dashboard").status_code == 401
    d = c.get("/reports/admin-dashboard", headers=s["admin"]["h"]).json()
    assert d["todays_orders"] == 3 and d["delivered_orders"] == 1
    assert d["cancelled_orders"] == 1 and d["rejected_orders"] == 1
    assert D(str(d["discounts_given"])) == D("20.00") and D(str(d["total_revenue"])) > 0
    assert d["online_delivery_partners"] == 1 and d["average_delivery_minutes"] is not None


def test_top_restaurants_and_coupon_usage(setup):
    w, s, c = setup["w"], setup, setup["w"].c
    w.coupon(s["admin"], code="FLAT20", discount_type="FLAT", discount_value=20, max_discount=None)
    delivered(setup, coupon="FLAT20")
    delivered(setup)
    top = c.get("/reports/top-restaurants", headers=s["admin"]["h"]).json()
    assert len(top) == 1 and top[0]["restaurant_name"] == "Spice Hub" and top[0]["order_count"] == 2
    assert c.get("/reports/top-restaurants?by=revenue", headers=s["admin"]["h"]).status_code == 200
    assert c.get("/reports/top-restaurants?by=zzz", headers=s["admin"]["h"]).status_code == 422
    usage = c.get("/reports/coupon-usage", headers=s["admin"]["h"]).json()
    assert usage[0]["code"] == "FLAT20" and usage[0]["uses"] == 1 and D(str(usage[0]["total_discount"])) == D("20.00")
    assert c.get("/reports/coupon-usage", headers=s["owner"]["h"]).status_code == 403


def test_restaurant_sales_report_and_ownership(setup):
    w, s, c = setup["w"], setup, setup["w"].c
    delivered(setup, qty=3)
    rid = s["restaurant"]["id"]
    rep = c.get(f"/reports/restaurant-sales?restaurant_id={rid}", headers=s["owner"]["h"]).json()
    assert rep["total_orders"] == 1 and len(rep["daily"]) == 1
    assert rep["best_selling_items"][0]["name"] == "Masala Dosa" and rep["best_selling_items"][0]["quantity_sold"] == 3
    assert rep["average_preparation_minutes"] is not None
    other = w.owner(s["admin"])
    assert c.get(f"/reports/restaurant-sales?restaurant_id={rid}", headers=other["h"]).status_code == 403
    assert c.get(f"/reports/restaurant-sales?restaurant_id={rid}", headers=s["admin"]["h"]).status_code == 200
    assert c.get(f"/reports/restaurant-sales?restaurant_id={rid}", headers=s["customer"]["h"]).status_code == 403
    assert c.get("/reports/restaurant-sales?restaurant_id=9999", headers=s["admin"]["h"]).status_code == 404


def test_partner_summary_access_rules(setup):
    w, s, c = setup["w"], setup, setup["w"].c
    delivered(setup)
    p = s["partner"]
    mine = c.get("/reports/partner-summary", headers=p["h"]).json()
    assert mine["completed_deliveries"] == 1 and D(str(mine["total_earnings"])) > D("25")
    assert D(str(mine["distance_travelled_km"])) >= 0 and len(mine["daily"]) == 1
    by_admin = c.get(f"/reports/partner-summary?partner_id={p['id']}", headers=s["admin"]["h"])
    assert by_admin.status_code == 200
    assert c.get("/reports/partner-summary", headers=s["admin"]["h"]).status_code == 400
    other = w.partner(s["admin"])
    assert c.get(f"/reports/partner-summary?partner_id={p['id']}", headers=other["h"]).status_code == 403
    assert c.get("/reports/partner-summary", headers=s["customer"]["h"]).status_code == 403
