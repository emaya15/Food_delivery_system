"""Level 11: scheduled job behaviour."""
from datetime import datetime, timedelta, timezone

from app.jobs import scheduler as sched
from app.models.coupon import Coupon
from app.models.order import Order
from app.models.user import DeliveryPartnerProfile
from app.services import coupon_service, delivery_service, order_service
from app.utils.timeutils import utcnow
from app.websockets.manager import manager
from tests.conftest import HQ


def test_auto_reject_stale_order_refunds_and_releases_coupon(setup, db):
    w, s = setup["w"], setup
    w.coupon(s["admin"], code="FLAT20", discount_type="FLAT", discount_value=20, max_discount=None, usage_limit_total=1)
    w.add_to_cart(s["customer"], s["item"]["id"], 1)
    w.c.post("/cart/apply-coupon", json={"code": "FLAT20"}, headers=s["customer"]["h"])
    order = w.place(s["customer"], s["address"]["id"], method="ONLINE").json()

    row = db.get(Order, order["id"])
    row.placed_at = utcnow() - timedelta(minutes=6)
    db.commit()
    manager.capture.clear()

    assert order_service.auto_reject_stale_orders(db) == 1
    db.expire_all()
    row = db.get(Order, order["id"])
    assert row.status == "Rejected" and row.rejection_reason == "Restaurant did not respond"
    assert row.payment_status == "Refunded"
    assert row.history[-1].changed_by == "System" and row.history[-1].to_status == "Rejected"
    assert db.query(Coupon).filter_by(code="FLAT20").one().used_count == 0
    assert any(m.get("type") == "order_auto_rejected" for _ch, m in manager.capture)
    assert order_service.auto_reject_stale_orders(db) == 0      # idempotent


def test_recent_orders_are_not_auto_rejected(placed_order, db):
    assert order_service.auto_reject_stale_orders(db) == 0
    assert db.get(Order, placed_order["id"]).status == "Placed"


def test_accepted_orders_are_not_auto_rejected(placed_order, setup, db):
    setup["w"].c.put(f"/orders/{placed_order['id']}/accept", json={"preparation_minutes": 10}, headers=setup["owner"]["h"])
    row = db.get(Order, placed_order["id"])
    row.placed_at = utcnow() - timedelta(minutes=30)
    db.commit()
    assert order_service.auto_reject_stale_orders(db) == 0


def test_stale_partners_go_offline(setup, db):
    w = setup["w"]
    stale = w.partner(setup["admin"], HQ[0], HQ[1])
    fresh = w.partner(setup["admin"], HQ[0], HQ[1])
    profile = db.query(DeliveryPartnerProfile).filter_by(user_id=stale["id"]).one()
    profile.last_location_at = utcnow() - timedelta(minutes=11)
    db.commit()
    assert delivery_service.set_offline_if_stale(db, 10) == 1
    db.expire_all()
    assert db.query(DeliveryPartnerProfile).filter_by(user_id=stale["id"]).one().is_online is False
    assert db.query(DeliveryPartnerProfile).filter_by(user_id=fresh["id"]).one().is_online is True


def test_expired_coupons_deactivated(setup, db):
    now = datetime.now(timezone.utc)
    db.add(Coupon(code="DEADBEEF", discount_type="FLAT", discount_value=5, valid_from=now - timedelta(days=5),
                  valid_until=now - timedelta(days=1), is_active=True))
    db.add(Coupon(code="LIVE", discount_type="FLAT", discount_value=5, valid_from=now - timedelta(days=1),
                  valid_until=now + timedelta(days=1), is_active=True))
    db.commit()
    assert coupon_service.deactivate_expired(db) == 1
    db.expire_all()
    assert db.query(Coupon).filter_by(code="DEADBEEF").one().is_active is False
    assert db.query(Coupon).filter_by(code="LIVE").one().is_active is True


def test_scheduler_registers_all_jobs_is_singleton_and_stops_cleanly():
    first = sched.start_scheduler()
    try:
        second = sched.start_scheduler()
        assert first is second and first.running
        ids = {j.id for j in first.get_jobs()}
        assert ids == {"auto_reject_orders", "expire_offers", "retry_unassigned", "partners_offline", "deactivate_coupons"}
    finally:
        sched.stop_scheduler()
    assert sched.get_scheduler() is None and not first.running
