"""Reports and dashboard (Level 15)."""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_admin, require_roles
from app.enums import Role
from app.models.user import User
from app.schemas.report import (
    AdminDashboardOut,
    CouponUsageOut,
    PartnerSummaryOut,
    RestaurantSalesOut,
    TopRestaurantOut,
)
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/admin-dashboard", response_model=AdminDashboardOut)
def dashboard(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return report_service.admin_dashboard(db)


@router.get("/top-restaurants", response_model=List[TopRestaurantOut])
def top_restaurants(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    by: str = Query("orders", pattern="^(orders|revenue)$"),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Top 10 restaurants by order count (default) or revenue; delivered orders only."""
    return report_service.top_restaurants(db, from_date, to_date, by)


@router.get("/coupon-usage", response_model=List[CouponUsageOut])
def coupon_usage(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return report_service.coupon_usage(db, from_date, to_date)


@router.get("/restaurant-sales", response_model=RestaurantSalesOut)
def restaurant_sales(
    restaurant_id: int,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    user: User = Depends(require_roles(Role.ADMIN, Role.RESTAURANT_OWNER)),
    db: Session = Depends(get_db),
):
    """Admins: any restaurant. Owners: only their own."""
    return report_service.restaurant_sales(db, user, restaurant_id, from_date, to_date)


@router.get("/partner-summary", response_model=PartnerSummaryOut)
def partner_summary(
    partner_id: Optional[int] = Query(None, description="Required for admins; partners see their own"),
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    user: User = Depends(require_roles(Role.ADMIN, Role.DELIVERY_PARTNER)),
    db: Session = Depends(get_db),
):
    return report_service.partner_summary(db, user, partner_id, from_date, to_date)
