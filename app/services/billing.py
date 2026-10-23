"""Pure billing logic (no database access) so it is trivially unit-testable.

Bill rules
----------
* item_total        = sum(unit_price * quantity)
* discount          = eligible coupon discount (never more than item_total)
* packaging_charges = sum(packaging_charge * quantity)
* delivery_fee      = 20 for the first 3 km + 8 per additional km (rounded up);
                      multiplied by 1.5 during surge windows (12-14h and 19-22h local)
* platform_fee      = 5
* gst               = 5% of (item_total - discount)
* tip               = optional, >= 0
* grand_total       = item_total - discount + packaging + delivery_fee + platform_fee + gst + tip
"""
import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable

from app.utils.constants import (
    BASE_DELIVERY_FEE,
    BASE_DELIVERY_KM,
    EXTRA_DELIVERY_FEE_PER_KM,
    GST_RATE,
    PARTNER_BASE_EARNING,
    PARTNER_EARNING_PER_KM,
    PLATFORM_FEE,
    SURGE_MULTIPLIER,
    SURGE_WINDOWS,
)
from app.utils.money import ZERO, money, to_decimal


@dataclass(frozen=True)
class BillLine:
    """One cart/order line used for billing."""

    unit_price: Decimal
    packaging_charge: Decimal
    quantity: int


@dataclass(frozen=True)
class Bill:
    """Full bill breakdown (all amounts are two-decimal ``Decimal`` values)."""

    item_total: Decimal
    discount: Decimal
    packaging_charges: Decimal
    delivery_fee: Decimal
    platform_fee: Decimal
    gst: Decimal
    tip: Decimal
    grand_total: Decimal
    surge_applied: bool


def is_surge_time(local_dt: datetime) -> bool:
    """True during 12 PM-2 PM and 7 PM-10 PM (local time)."""
    return any(start <= local_dt.hour < end for start, end in SURGE_WINDOWS)


def base_delivery_fee(distance_km) -> Decimal:
    """Delivery fee without surge: 20 for first 3 km, +8 per additional km (rounded up)."""
    distance = to_decimal(distance_km)
    if distance <= BASE_DELIVERY_KM:
        return money(BASE_DELIVERY_FEE)
    extra_km = int(math.ceil(distance - BASE_DELIVERY_KM))
    return money(BASE_DELIVERY_FEE + EXTRA_DELIVERY_FEE_PER_KM * extra_km)


def calculate_delivery_fee(distance_km, surge: bool = False) -> Decimal:
    """Delivery fee with optional 1.5x surge multiplier."""
    fee = base_delivery_fee(distance_km)
    return money(fee * SURGE_MULTIPLIER) if surge else fee


def calculate_item_total(lines: Iterable[BillLine]) -> Decimal:
    return money(sum((to_decimal(l.unit_price) * l.quantity for l in lines), Decimal("0")))


def calculate_packaging(lines: Iterable[BillLine]) -> Decimal:
    return money(sum((to_decimal(l.packaging_charge) * l.quantity for l in lines), Decimal("0")))


def calculate_bill(
    lines: "list[BillLine]",
    discount,
    distance_km,
    tip=0,
    when_local: "datetime | None" = None,
) -> Bill:
    """Compute the complete bill for an order."""
    item_total = calculate_item_total(lines)
    discount_amt = money(min(to_decimal(discount), item_total))
    packaging = calculate_packaging(lines)
    surge = bool(when_local and is_surge_time(when_local))
    delivery_fee = calculate_delivery_fee(distance_km, surge)
    platform_fee = money(PLATFORM_FEE)
    gst = money((item_total - discount_amt) * GST_RATE)
    tip_amt = money(tip)
    if tip_amt < ZERO:
        raise ValueError("tip cannot be negative")
    grand_total = money(item_total - discount_amt + packaging + delivery_fee + platform_fee + gst + tip_amt)
    return Bill(
        item_total=item_total,
        discount=discount_amt,
        packaging_charges=packaging,
        delivery_fee=delivery_fee,
        platform_fee=platform_fee,
        gst=gst,
        tip=tip_amt,
        grand_total=grand_total,
        surge_applied=surge,
    )


def calculate_partner_earning(distance_km, tip=0) -> Decimal:
    """Partner earning: 25 base + 6 per km + customer tip."""
    return money(PARTNER_BASE_EARNING + PARTNER_EARNING_PER_KM * to_decimal(distance_km) + to_decimal(tip))
