"""Aggregated reports. All aggregation is done in SQL; only per-day bucketing of
(at most one date range of) rows happens in Python so local-timezone days are exact."""
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.enums import OrderStatus, Role
from app.models.coupon import Coupon
from app.models.order import Order, OrderItem
from app.models.restaurant import Restaurant
from app.models.user import DeliveryPartnerProfile, User
from app.schemas.report import (
    AdminDashboardOut,
    BestSellingItem,
    CouponUsageOut,
    PartnerDay,
    PartnerSummaryOut,
    RestaurantSalesOut,
    SalesDay,
    TopRestaurantOut,
)
from app.utils.errors import BadRequestError, ForbiddenError, NotFoundError
from app.utils.money import ZERO, money, to_decimal
from app.utils.timeutils import ensure_aware, local_day_bounds_utc, local_range_bounds_utc, local_today, to_local

DELIVERED = OrderStatus.DELIVERED.value


def _range(from_date: Optional[date], to_date: Optional[date], default_days: int = 30):
    from datetime import timedelta

    to_date = to_date or local_today()
    from_date = from_date or (to_date - timedelta(days=default_days - 1))
    if to_date < from_date:
        raise BadRequestError("to_date must not be before from_date")
    return from_date, to_date, *local_range_bounds_utc(from_date, to_date)


def admin_dashboard(db: Session) -> AdminDashboardOut:
    today = local_today()
    start, end = local_day_bounds_utc(today)
    in_day = (Order.placed_at >= start, Order.placed_at < end)
    row = db.execute(
        select(
            func.count(Order.id),
            func.coalesce(func.sum(case((Order.status == DELIVERED, 1), else_=0)), 0),
            func.coalesce(func.sum(case((Order.status == OrderStatus.CANCELLED.value, 1), else_=0)), 0),
            func.coalesce(func.sum(case((Order.status == OrderStatus.REJECTED.value, 1), else_=0)), 0),
            func.coalesce(func.sum(case((Order.status == DELIVERED, Order.grand_total), else_=0)), 0),
            func.coalesce(func.sum(case((Order.status == DELIVERED, Order.discount), else_=0)), 0),
        ).where(*in_day)
    ).one()
    online = db.scalar(
        select(func.count(DeliveryPartnerProfile.id))
        .join(User, User.id == DeliveryPartnerProfile.user_id)
        .where(DeliveryPartnerProfile.is_online.is_(True), User.is_active.is_(True))
    ) or 0
    # Average delivery time (placed -> delivered) for orders delivered today.
    pairs = db.execute(
        select(Order.placed_at, Order.delivered_at).where(
            Order.status == DELIVERED, Order.delivered_at >= start, Order.delivered_at < end
        )
    ).all()
    avg_minutes = None
    if pairs:
        total = sum((ensure_aware(d) - ensure_aware(p)).total_seconds() for p, d in pairs)
        avg_minutes = round(total / len(pairs) / 60, 2)
    return AdminDashboardOut(
        date=today,
        todays_orders=row[0] or 0,
        delivered_orders=int(row[1]),
        cancelled_orders=int(row[2]),
        rejected_orders=int(row[3]),
        total_revenue=money(row[4]),
        discounts_given=money(row[5]),
        online_delivery_partners=online,
        average_delivery_minutes=avg_minutes,
    )


def top_restaurants(db: Session, from_date: Optional[date], to_date: Optional[date], by: str = "orders") -> List[TopRestaurantOut]:
    if by not in ("orders", "revenue"):
        raise BadRequestError("by must be 'orders' or 'revenue'")
    _f, _t, start, end = _range(from_date, to_date)
    count_col = func.count(Order.id).label("order_count")
    revenue_col = func.coalesce(func.sum(Order.grand_total), 0).label("revenue")
    stmt = (
        select(Restaurant.id, Restaurant.name, count_col, revenue_col)
        .join(Order, Order.restaurant_id == Restaurant.id)
        .where(Order.status == DELIVERED, Order.placed_at >= start, Order.placed_at < end)
        .group_by(Restaurant.id, Restaurant.name)
    )
    order_cols = (count_col.desc(), revenue_col.desc()) if by == "orders" else (revenue_col.desc(), count_col.desc())
    rows = db.execute(stmt.order_by(*order_cols, Restaurant.id).limit(10)).all()
    return [TopRestaurantOut(restaurant_id=r[0], restaurant_name=r[1], order_count=r[2], revenue=money(r[3])) for r in rows]


def coupon_usage(db: Session, from_date: Optional[date], to_date: Optional[date]) -> List[CouponUsageOut]:
    _f, _t, start, end = _range(from_date, to_date)
    rows = db.execute(
        select(
            Coupon.id,
            Coupon.code,
            func.count(Order.id),
            func.coalesce(func.sum(Order.discount), 0),
            func.coalesce(func.sum(Order.grand_total), 0),
        )
        .join(Order, Order.coupon_id == Coupon.id)
        .where(
            Order.status.notin_([OrderStatus.CANCELLED.value, OrderStatus.REJECTED.value]),
            Order.placed_at >= start,
            Order.placed_at < end,
        )
        .group_by(Coupon.id, Coupon.code)
        .order_by(func.count(Order.id).desc(), Coupon.id)
    ).all()
    return [CouponUsageOut(coupon_id=r[0], code=r[1], uses=r[2], total_discount=money(r[3]), revenue=money(r[4])) for r in rows]


def restaurant_sales(
    db: Session, user: User, restaurant_id: int, from_date: Optional[date], to_date: Optional[date]
) -> RestaurantSalesOut:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFoundError("Restaurant not found")
    if user.role == Role.RESTAURANT_OWNER.value and restaurant.owner_id != user.id:
        raise ForbiddenError("You can only view reports for your own restaurants")
    f, t, start, end = _range(from_date, to_date)
    orders = db.execute(
        select(Order.placed_at, Order.grand_total, Order.accepted_at, Order.ready_at).where(
            Order.restaurant_id == restaurant_id,
            Order.status == DELIVERED,
            Order.placed_at >= start,
            Order.placed_at < end,
        )
    ).all()
    daily_map = defaultdict(lambda: [0, ZERO])
    prep = []
    for placed, total, accepted, ready in orders:
        bucket = daily_map[to_local(placed).date()]
        bucket[0] += 1
        bucket[1] += to_decimal(total)
        if accepted is not None and ready is not None:
            prep.append((ensure_aware(ready) - ensure_aware(accepted)).total_seconds() / 60)
    best = db.execute(
        select(OrderItem.name, func.sum(OrderItem.quantity), func.sum(OrderItem.line_total))
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.restaurant_id == restaurant_id,
            Order.status == DELIVERED,
            Order.placed_at >= start,
            Order.placed_at < end,
        )
        .group_by(OrderItem.name)
        .order_by(func.sum(OrderItem.quantity).desc(), OrderItem.name)
        .limit(10)
    ).all()
    return RestaurantSalesOut(
        restaurant_id=restaurant.id,
        restaurant_name=restaurant.name,
        from_date=f,
        to_date=t,
        total_orders=len(orders),
        total_sales=money(sum((to_decimal(o[1]) for o in orders), Decimal("0"))),
        average_preparation_minutes=round(sum(prep) / len(prep), 2) if prep else None,
        daily=[SalesDay(date=d, orders=v[0], sales=money(v[1])) for d, v in sorted(daily_map.items())],
        best_selling_items=[BestSellingItem(name=b[0], quantity_sold=int(b[1]), revenue=money(b[2])) for b in best],
    )


def partner_summary(
    db: Session, user: User, partner_id: Optional[int], from_date: Optional[date], to_date: Optional[date]
) -> PartnerSummaryOut:
    if user.role == Role.DELIVERY_PARTNER.value:
        if partner_id is not None and partner_id != user.id:
            raise ForbiddenError("You can only view your own summary")
        partner_id = user.id
    elif partner_id is None:
        raise BadRequestError("partner_id is required")
    partner = db.get(User, partner_id)
    if partner is None or partner.role != Role.DELIVERY_PARTNER.value:
        raise NotFoundError("Delivery partner not found")
    f, t, start, end = _range(from_date, to_date)
    rows = db.execute(
        select(Order.delivered_at, Order.distance_km, Order.partner_earning).where(
            Order.partner_id == partner_id,
            Order.status == DELIVERED,
            Order.delivered_at >= start,
            Order.delivered_at < end,
        )
    ).all()
    daily = defaultdict(lambda: [0, ZERO, ZERO])
    for delivered, km, earning in rows:
        b = daily[to_local(delivered).date()]
        b[0] += 1
        b[1] += to_decimal(km)
        b[2] += to_decimal(earning)
    return PartnerSummaryOut(
        partner_id=partner.id,
        partner_name=partner.name,
        from_date=f,
        to_date=t,
        completed_deliveries=len(rows),
        distance_travelled_km=money(sum((to_decimal(r[1]) for r in rows), Decimal("0"))),
        total_earnings=money(sum((to_decimal(r[2]) for r in rows), Decimal("0"))),
        daily=[PartnerDay(date=d, deliveries=v[0], distance_km=money(v[1]), earnings=money(v[2])) for d, v in sorted(daily.items())],
    )
