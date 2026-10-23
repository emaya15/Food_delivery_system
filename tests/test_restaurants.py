"""Levels 3, 4, 14: restaurants, menus, addresses, nearby search."""
from tests.conftest import FAR, HQ


def test_restaurant_ownership_enforced(setup):
    w, c = setup["w"], setup["w"].c
    other = w.owner(setup["admin"])
    rid = setup["restaurant"]["id"]
    assert c.put(f"/restaurants/{rid}", json={"name": "Hijack"}, headers=other["h"]).status_code == 403
    assert c.put(f"/restaurants/{rid}/open-status", json={"is_temporarily_closed": True}, headers=other["h"]).status_code == 403
    assert c.post(f"/restaurants/{rid}/categories", json={"name": "Drinks"}, headers=other["h"]).status_code == 403
    assert c.put(f"/menu-items/{setup['item']['id']}", json={"name": "Zzz"}, headers=other["h"]).status_code == 403
    mine = c.get("/restaurants/me", headers=setup["owner"]["h"]).json()
    assert [r["id"] for r in mine] == [rid]
    assert c.get("/restaurants/me", headers=other["h"]).json() == []


def test_customer_cannot_create_restaurant(setup):
    r = setup["w"].c.post("/restaurants", json={}, headers=setup["customer"]["h"])
    assert r.status_code == 403


def test_opening_must_be_before_closing(world, client):
    admin = world.admin()
    owner = world.owner(admin)
    payload = {"name": "Roma Pizza", "cuisine_type": "Pizza", "address": "Somewhere", "latitude": 17.4, "longitude": 78.4,
               "opening_time": "22:00:00", "closing_time": "09:00:00"}
    assert client.post("/restaurants", json=payload, headers=owner["h"]).status_code == 422


def test_invalid_coordinates_rejected(world, client):
    admin = world.admin()
    owner = world.owner(admin)
    payload = {"name": "Roma Pizza", "cuisine_type": "Pizza", "address": "Somewhere", "latitude": 123, "longitude": 78.4,
               "opening_time": "09:00:00", "closing_time": "22:00:00"}
    assert client.post("/restaurants", json=payload, headers=owner["h"]).status_code == 422


def test_menu_grouped_by_category_with_unavailable_marked(setup):
    w, c, rid = setup["w"], setup["w"].c, setup["restaurant"]["id"]
    owner = setup["owner"]
    second = w.menu_item(owner, rid, name="Idli", price=60, packaging=5)
    assert c.put(f"/menu-items/{second['id']}/availability", json={"is_available": False}, headers=owner["h"]).status_code == 200
    menu = c.get(f"/restaurants/{rid}/menu", headers=setup["customer"]["h"]).json()
    items = {i["name"]: i for cat in menu["categories"] for i in cat["items"]}
    assert items["Idli"]["is_available"] is False and items["Idli"]["availability"] == "Unavailable"
    assert items["Masala Dosa"]["availability"] == "Available"


def test_menu_item_soft_delete_keeps_history(setup):
    w, c = setup["w"], setup["w"].c
    assert w.add_to_cart(setup["customer"], setup["item"]["id"], 1).status_code == 201
    order = w.place(setup["customer"], setup["address"]["id"]).json()
    assert c.delete(f"/menu-items/{setup['item']['id']}", headers=setup["owner"]["h"]).status_code == 204
    menu = c.get(f"/restaurants/{setup['restaurant']['id']}/menu", headers=setup["customer"]["h"]).json()
    assert all(not cat["items"] for cat in menu["categories"])
    again = c.get(f"/orders/{order['id']}", headers=setup["customer"]["h"]).json()
    assert again["items"][0]["name"] == "Masala Dosa"
    assert w.add_to_cart(setup["customer"], setup["item"]["id"], 1).status_code == 404


def test_menu_item_validation(setup):
    w, c, rid = setup["w"], setup["w"].c, setup["restaurant"]["id"]
    cat = c.get(f"/restaurants/{rid}/menu", headers=setup["owner"]["h"]).json()["categories"][0]["category_id"]
    bad = c.post(f"/restaurants/{rid}/menu-items", json={"category_id": cat, "name": "Free", "price": 0},
                 headers=setup["owner"]["h"])
    assert bad.status_code == 422
    wrong_cat = c.post(f"/restaurants/{rid}/menu-items", json={"category_id": 9999, "name": "Ghost", "price": 10},
                       headers=setup["owner"]["h"])
    assert wrong_cat.status_code == 400


def test_addresses_single_default_and_isolation(setup):
    w, c = setup["w"], setup["w"].c
    cust = setup["customer"]
    first = setup["address"]
    assert first["is_default"] is True
    second = w.address(cust)
    assert second["is_default"] is False
    assert c.put(f"/addresses/{second['id']}/default", headers=cust["h"]).status_code == 200
    items = c.get("/addresses", headers=cust["h"]).json()["items"]
    assert sum(1 for a in items if a["is_default"]) == 1
    assert next(a for a in items if a["id"] == second["id"])["is_default"] is True
    stranger = w.customer()
    assert c.put(f"/addresses/{first['id']}", json={"city": "Pune"}, headers=stranger["h"]).status_code == 404
    assert c.delete(f"/addresses/{first['id']}", headers=stranger["h"]).status_code == 404
    assert c.delete(f"/addresses/{second['id']}", headers=cust["h"]).status_code == 204
    left = c.get("/addresses", headers=cust["h"]).json()["items"]
    assert len(left) == 1 and left[0]["is_default"] is True  # default promoted


def test_address_validation(setup):
    c = setup["w"].c
    body = {"label": "Home", "address_line": "Line 1", "city": "Hyd", "pincode": "123", "latitude": 17, "longitude": 78}
    assert c.post("/addresses", json=body, headers=setup["customer"]["h"]).status_code == 422
    body.update(pincode="500081", label="Office")
    assert c.post("/addresses", json=body, headers=setup["customer"]["h"]).status_code == 422


def test_nearby_returns_open_in_radius_sorted_with_distance(setup):
    w, c = setup["w"], setup["w"].c
    owner2 = w.owner(setup["admin"])
    w.restaurant(owner2, name="Farther Place", latitude=17.4700, longitude=78.4100)  # ~3 km
    w.restaurant(owner2, name="Too Far", latitude=FAR[0], longitude=FAR[1])
    closed = w.restaurant(owner2, name="Closed Now")
    c.put(f"/restaurants/{closed['id']}/open-status", json={"is_temporarily_closed": True}, headers=owner2["h"])
    r = c.get(f"/restaurants/nearby?latitude={HQ[0]}&longitude={HQ[1]}", headers=setup["customer"]["h"])
    assert r.status_code == 200
    names = [x["name"] for x in r.json()["items"]]
    assert names == ["Spice Hub", "Farther Place"]
    first = r.json()["items"][0]
    assert first["distance_km"] == 0 and first["estimated_delivery_minutes"] == 20
    assert r.json()["items"][1]["distance_km"] > 0


def test_nearby_filters_and_validation(setup):
    w, c = setup["w"], setup["w"].c
    owner2 = w.owner(setup["admin"])
    w.restaurant(owner2, name="Pizza Planet", cuisine_type="Pizza")
    h = setup["customer"]["h"]
    base = f"/restaurants/nearby?latitude={HQ[0]}&longitude={HQ[1]}"
    assert [x["name"] for x in c.get(base + "&cuisine=pizza", headers=h).json()["items"]] == ["Pizza Planet"]
    assert [x["name"] for x in c.get(base + "&search=spice", headers=h).json()["items"]] == ["Spice Hub"]
    assert c.get(base + "&min_rating=4", headers=h).json()["total"] == 0
    assert c.get(base + "&limit=1", headers=h).json()["items"].__len__() == 1
    assert c.get("/restaurants/nearby?latitude=200&longitude=10", headers=h).status_code == 422
    assert c.get(base + "&sort_by=bogus", headers=h).status_code == 422
    assert c.get(base + "&limit=0", headers=h).status_code == 422


def test_nearby_has_coupon_filter(setup):
    w, c = setup["w"], setup["w"].c
    owner2 = w.owner(setup["admin"])
    w.restaurant(owner2, name="No Coupon")
    w.coupon(setup["owner"], code="SPICE5", restaurant_id=setup["restaurant"]["id"])
    r = c.get(f"/restaurants/nearby?latitude={HQ[0]}&longitude={HQ[1]}&has_coupon=true", headers=setup["customer"]["h"])
    assert [x["name"] for x in r.json()["items"]] == ["Spice Hub"]
