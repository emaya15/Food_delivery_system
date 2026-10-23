"""Report schemas."""
from datetime import date
from typing import List, Optional

from pydantic import BaseModel

from app.schemas.common import Money


class AdminDashboardOut(BaseModel):
    date: date
    todays_orders: int
    delivered_orders: int
    cancelled_orders: int
    rejected_orders: int
    total_revenue: Money
    discounts_given: Money
    online_delivery_partners: int
    average_delivery_minutes: Optional[float] = None


class TopRestaurantOut(BaseModel):
    restaurant_id: int
    restaurant_name: str
    order_count: int
    revenue: Money


class CouponUsageOut(BaseModel):
    coupon_id: int
    code: str
    uses: int
    total_discount: Money
    revenue: Money


class SalesDay(BaseModel):
    date: date
    orders: int
    sales: Money


class BestSellingItem(BaseModel):
    name: str
    quantity_sold: int
    revenue: Money


class RestaurantSalesOut(BaseModel):
    restaurant_id: int
    restaurant_name: str
    from_date: date
    to_date: date
    total_orders: int
    total_sales: Money
    average_preparation_minutes: Optional[float] = None
    daily: List[SalesDay]
    best_selling_items: List[BestSellingItem]


class PartnerDay(BaseModel):
    date: date
    deliveries: int
    distance_km: Money
    earnings: Money


class PartnerSummaryOut(BaseModel):
    partner_id: int
    partner_name: str
    from_date: date
    to_date: date
    completed_deliveries: int
    distance_travelled_km: Money
    total_earnings: Money
    daily: List[PartnerDay]
