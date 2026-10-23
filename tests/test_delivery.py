"""Level 9: assignment, offers, pickup, OTP delivery, earnings."""
from datetime import timedelta
from decimal import Decimal as D

from app.models.delivery import AdminNotification, DeliveryOffer
from app.models.order import Order
from app.services import assignment_service
from app.utils.timeutils import utcnow
from tests.conftest import HQ


def accept_order(setup, order, minutes=15):
    r = setup["w"].c.put(f"/orders/{order['id']}/accept", json={"preparation_minutes": minutes}, headers=setup["owner"]["h"])
    assert r.status_code == 200, r.text
    return r.json()


def offers(setup, partner):
    r = setup["w"].c.get("/partners/me/offers", headers=partner["h"])
    assert r.status_code == 200
    return r.json()["items"]


def test_nearest_partner_is_offered_first_and_far_partner_excluded(setup, placed_order):
    w = setup["w"]
    near = w.partner(setup["admin"], HQ[0] + 0.005, HQ[1])      # ~0.55 km
    nearer = w.partner(setup["admin"], HQ[0] + 0.001, HQ[1])    # ~0.11 km
    far = w.partner(setup["admin"], HQ[0] + 0.2, HQ[1])         # ~22 km -> outside 5 km
    accept_order(setup, placed_order)
    assert len(offers(setup, nearer)) == 1
    assert offers(setup, near) == [] and offers(setup, far) == []
    o = offers(setup, nearer)[0]
    assert o["restaurant_name"] == "Spice Hub" and o["seconds_remaining"] > 0
    assert D(str(o["expected_earning"])) > D("25")


def test_offline_unapproved_and_busy_partners_are_skipped(setup, placed_order):
    w = setup["w"]
    offline = w.partner(setup["admin"], online=False)
    online = w.partner(setup["admin"], HQ[0] + 0.01, HQ[1])
    accept_order(setup, placed_order)
    assert offers(setup, offline) == []
    assert len(offers(setup, online)) == 1


def test_decline_moves_to_next_partner(setup, placed_order):
    w, c = setup["w"], setup["w"].c
    p1 = w.partner(setup["admin"], HQ[0] + 0.001, HQ[1])
    p2 = w.partner(setup["admin"], HQ[0] + 0.01, HQ[1])
    accept_order(setup, placed_order)
    first = offers(setup, p1)[0]
    assert c.put(f"/offers/{first['id']}/decline", headers=p1["h"]).status_code == 200
    assert offers(setup, p1) == [] and len(offers(setup, p2)) == 1


def test_offer_expiry_job_offers_to_next_partner(setup, placed_order, db):
    w = setup["w"]
    p1 = w.partner(setup["admin"], HQ[0] + 0.001, HQ[1])
    p2 = w.partner(setup["admin"], HQ[0] + 0.01, HQ[1])
    accept_order(setup, placed_order)
    offer = db.query(DeliveryOffer).filter_by(partner_id=p1["id"]).one()
    offer.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert assignment_service.expire_offers(db) == 1
    db.expire_all()
    assert db.query(DeliveryOffer).filter_by(partner_id=p1["id"]).one().status == "Expired"
    assert len(offers(setup, p2)) == 1
    # an expired offer can no longer be accepted
    assert w.c.put(f"/offers/{offer.id}/accept", headers=p1["h"]).status_code == 409


def test_expired_pending_offer_cannot_be_accepted(setup, placed_order, db):
    w = setup["w"]
    p1 = w.partner(setup["admin"], HQ[0] + 0.001, HQ[1])
    accept_order(setup, placed_order)
    offer = db.query(DeliveryOffer).one()
    offer.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert w.c.put(f"/offers/{offer.id}/accept", headers=p1["h"]).status_code == 400


def test_only_one_partner_can_win_an_order(setup, placed_order, db):
    """Second acceptance fails. (True parallel locking needs MySQL; see README.)"""
    w, c = setup["w"], setup["w"].c
    p1 = w.partner(setup["admin"], HQ[0] + 0.001, HQ[1])
    p2 = w.partner(setup["admin"], HQ[0] + 0.01, HQ[1])
    accept_order(setup, placed_order)
    offer1 = db.query(DeliveryOffer).filter_by(partner_id=p1["id"]).one()
    # force a second, simultaneously live offer for the same order
    now = utcnow()
    db.add(DeliveryOffer(order_id=placed_order["id"], partner_id=p2["id"], status="Pending", pickup_distance_km=1,
                         delivery_distance_km=1, expected_earning=30, offered_at=now, expires_at=now + timedelta(seconds=30)))
    db.commit()
    offer2 = db.query(DeliveryOffer).filter_by(partner_id=p2["id"]).one()
    assert c.put(f"/offers/{offer1.id}/accept", headers=p1["h"]).status_code == 200
    r = c.put(f"/offers/{offer2.id}/accept", headers=p2["h"])
    assert r.status_code == 409
    db.expire_all()
    assert db.get(Order, placed_order["id"]).partner_id == p1["id"]


def test_partner_cannot_accept_someone_elses_offer(setup, placed_order, db):
    w = setup["w"]
    p1 = w.partner(setup["admin"], HQ[0] + 0.001, HQ[1])
    p2 = w.partner(setup["admin"], HQ[0] + 0.01, HQ[1])
    accept_order(setup, placed_order)
    offer = db.query(DeliveryOffer).filter_by(partner_id=p1["id"]).one()
    assert w.c.put(f"/offers/{offer.id}/accept", headers=p2["h"]).status_code == 404


def full_flow_until_out_for_delivery(setup, order, partner):
    c, h_owner = setup["w"].c, setup["owner"]["h"]
    accept_order(setup, order)
    offer = offers(setup, partner)[0]
    assert c.put(f"/offers/{offer['id']}/accept", headers=partner["h"]).status_code == 200
    # pickup before ready is refused
    assert c.put(f"/orders/{order['id']}/pickup", headers=partner["h"]).status_code == 400
    c.put(f"/orders/{order['id']}/preparing", headers=h_owner)
    c.put(f"/orders/{order['id']}/ready", headers=h_owner)
    assert c.put(f"/orders/{order['id']}/pickup", headers=partner["h"]).json()["status"] == "Picked Up"
    assert c.put(f"/orders/{order['id']}/out-for-delivery", headers=partner["h"]).json()["status"] == "Out for Delivery"


def test_full_delivery_with_otp_cod_paid_and_earnings(setup, placed_order):
    w, c = setup["w"], setup["w"].c
    p = w.partner(setup["admin"], HQ[0] + 0.001, HQ[1])
    full_flow_until_out_for_delivery(setup, placed_order, p)
    otp = placed_order["delivery_otp"]
    done = c.put(f"/orders/{placed_order['id']}/deliver", json={"otp": otp}, headers=p["h"])
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "Delivered" and body["payment_status"] == "Paid" and body["delivered_at"]
    assert body["picked_up_at"] and body["status_history"][-1]["to_status"] == "Delivered"
    earn = c.get("/partners/me/earnings", headers=p["h"]).json()
    km = D(str(placed_order["distance_km"]))
    assert earn["completed_deliveries"] == 1
    assert D(str(earn["total_earnings"])) == D("25") + D("6") * km + D(str(placed_order["tip"]))
    rng = c.get("/partners/me/earnings?from_date=2000-01-01&to_date=2100-01-01", headers=p["h"]).json()
    assert rng["completed_deliveries"] == 1 and len(rng["daily"]) == 1
    assert c.get("/partners/me/earnings?from_date=2100-01-01&to_date=2000-01-01", headers=p["h"]).status_code == 400


def test_pickup_restricted_to_assigned_partner(setup, placed_order):
    w, c = setup["w"], setup["w"].c
    p1 = w.partner(setup["admin"], HQ[0] + 0.001, HQ[1])
    p2 = w.partner(setup["admin"], HQ[0] + 0.01, HQ[1])
    accept_order(setup, placed_order)
    c.put(f"/offers/{offers(setup, p1)[0]['id']}/accept", headers=p1["h"])
    c.put(f"/orders/{placed_order['id']}/preparing", headers=setup["owner"]["h"])
    c.put(f"/orders/{placed_order['id']}/ready", headers=setup["owner"]["h"])
    assert c.put(f"/orders/{placed_order['id']}/pickup", headers=p2["h"]).status_code == 403
    assert c.put(f"/orders/{placed_order['id']}/pickup", headers=p1["h"]).status_code == 200


def test_wrong_otp_is_400_and_three_failures_lock_and_notify_admin(setup, placed_order, db):
    w, c = setup["w"], setup["w"].c
    p = w.partner(setup["admin"], HQ[0] + 0.001, HQ[1])
    full_flow_until_out_for_delivery(setup, placed_order, p)
    otp = placed_order["delivery_otp"]
    wrong = "0000" if otp != "0000" else "1111"
    for expected_left in (2, 1):
        r = c.put(f"/orders/{placed_order['id']}/deliver", json={"otp": wrong}, headers=p["h"])
        assert r.status_code == 400 and f"{expected_left} attempt" in r.json()["error"]["message"]
    r = c.put(f"/orders/{placed_order['id']}/deliver", json={"otp": wrong}, headers=p["h"])
    assert r.status_code == 400 and "locked" in r.json()["error"]["message"]
    db.expire_all()
    order = db.get(Order, placed_order["id"])
    assert order.otp_attempts == 3 and order.otp_locked is True and order.status == "Out for Delivery"
    assert db.query(AdminNotification).filter_by(type="otp_locked").count() == 1
    # even the correct OTP is refused once locked
    assert c.put(f"/orders/{placed_order['id']}/deliver", json={"otp": otp}, headers=p["h"]).status_code == 403


def test_otp_format_validated(setup, placed_order):
    w, c = setup["w"], setup["w"].c
    p = w.partner(setup["admin"], HQ[0] + 0.001, HQ[1])
    full_flow_until_out_for_delivery(setup, placed_order, p)
    for bad in ("12", "12345", "abcd"):
        assert c.put(f"/orders/{placed_order['id']}/deliver", json={"otp": bad}, headers=p["h"]).status_code == 422


def test_partner_with_active_delivery_gets_no_new_offer_and_cannot_go_offline(setup, placed_order):
    w, c = setup["w"], setup["w"].c
    p = w.partner(setup["admin"], HQ[0] + 0.001, HQ[1])
    accept_order(setup, placed_order)
    c.put(f"/offers/{offers(setup, p)[0]['id']}/accept", headers=p["h"])
    assert c.put("/partners/me/availability", json={"is_online": False}, headers=p["h"]).status_code == 400
    # second order must not be offered to the busy partner
    w.add_to_cart(setup["customer"], setup["item"]["id"], 1)
    second = w.place(setup["customer"], setup["address"]["id"]).json()
    accept_order(setup, second)
    assert offers(setup, p) == []


def test_unassigned_order_alerts_admin_after_15_minutes(setup, placed_order, db):
    accept_order(setup, placed_order)            # no partners online
    assert assignment_service.retry_unassigned(db) == 0
    order = db.get(Order, placed_order["id"])
    order.accepted_at = utcnow() - timedelta(minutes=16)
    db.commit()
    assert assignment_service.retry_unassigned(db) == 1
    assert assignment_service.retry_unassigned(db) == 0          # only alerts once
    assert db.query(AdminNotification).filter_by(type="order_unassigned").count() == 1


def test_retry_job_assigns_when_a_partner_comes_online_later(setup, placed_order, db):
    w = setup["w"]
    accept_order(setup, placed_order)
    p = w.partner(setup["admin"], HQ[0] + 0.001, HQ[1])
    assert offers(setup, p) == []
    assignment_service.retry_unassigned(db)
    assert len(offers(setup, p)) == 1


def test_role_enforcement_on_partner_endpoints(setup):
    c = setup["w"].c
    assert c.put("/partners/me/location", json={"latitude": 1, "longitude": 1}, headers=setup["customer"]["h"]).status_code == 403
    assert c.get("/partners/me/earnings", headers=setup["owner"]["h"]).status_code == 403
    p = setup["w"].partner(setup["admin"])
    assert c.put("/partners/me/location", json={"latitude": 100, "longitude": 1}, headers=p["h"]).status_code == 422
