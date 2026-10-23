"""Pure unit tests: billing maths and Haversine."""
from datetime import datetime
from decimal import Decimal as D

import pytest

from app.services import billing
from app.utils.geo import estimated_delivery_minutes, haversine_km, travel_minutes


def test_haversine_zero_and_known_distance():
    assert haversine_km(17.4486, 78.3908, 17.4486, 78.3908) == 0
    # Hyderabad (Hitech City) -> Charminar is roughly 13 km
    assert 12.0 < haversine_km(17.4486, 78.3908, 17.3616, 78.4747) < 14.5


def test_estimated_time_uses_20_kmph():
    assert travel_minutes(5) == 15
    assert estimated_delivery_minutes(20, 5) == 35


@pytest.mark.parametrize("km,fee", [(0.5, "20.00"), (3, "20.00"), (3.01, "28.00"), (4, "28.00"), (5, "36.00"), (6.2, "52.00")])
def test_delivery_fee_rounds_up_extra_km(km, fee):
    assert billing.calculate_delivery_fee(km) == D(fee)


def test_surge_multiplier_and_windows():
    assert billing.calculate_delivery_fee(5, surge=True) == D("54.00")
    assert billing.is_surge_time(datetime(2026, 10, 21, 12, 0))
    assert billing.is_surge_time(datetime(2026, 10, 21, 21, 59))
    assert not billing.is_surge_time(datetime(2026, 10, 21, 14, 0))
    assert not billing.is_surge_time(datetime(2026, 10, 21, 10, 0))


def test_full_bill_matches_spec_formula():
    lines = [billing.BillLine(D("100"), D("5"), 2), billing.BillLine(D("50.50"), D("2"), 1)]
    bill = billing.calculate_bill(lines, D("30"), 4.2, tip=10, when_local=datetime(2026, 10, 21, 10, 0))
    assert bill.item_total == D("250.50")
    assert bill.packaging_charges == D("12.00")
    assert bill.delivery_fee == D("36.00")            # 20 + 2 extra km * 8
    assert bill.platform_fee == D("5.00")
    assert bill.gst == D("11.03")                     # 5% of (250.50 - 30)
    assert bill.grand_total == D("250.50") - D("30") + D("12") + D("36") + D("5") + D("11.03") + D("10")


def test_discount_never_exceeds_item_total():
    bill = billing.calculate_bill([billing.BillLine(D("40"), D("0"), 1)], D("100"), 1)
    assert bill.discount == D("40.00") and bill.gst == D("0.00")


def test_partner_earning_formula():
    assert billing.calculate_partner_earning(4, 10) == D("59.00")  # 25 + 6*4 + 10
