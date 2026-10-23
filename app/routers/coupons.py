"""Coupon management endpoints (Level 6)."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import pagination, require_approved_roles, require_customer
from app.enums import DiscountType, Role
from app.models.user import User
from app.schemas.cart import CouponCreate, CouponOut, CouponPreviewOut, CouponUpdate
from app.schemas.common import Page
from app.services import coupon_service
from app.utils.pagination import PageParams

router = APIRouter(prefix="/coupons", tags=["Coupons"])
manager = require_approved_roles(Role.ADMIN, Role.RESTAURANT_OWNER)


@router.post("", response_model=CouponOut, status_code=status.HTTP_201_CREATED)
def create_coupon(data: CouponCreate, user: User = Depends(manager), db: Session = Depends(get_db)):
    """Admins create platform-wide or restaurant coupons; owners only for their own restaurants."""
    return coupon_service.create_coupon(db, user, data)


@router.get("", response_model=Page[CouponOut])
def list_coupons(
    restaurant_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    discount_type: Optional[DiscountType] = None,
    page: PageParams = Depends(pagination),
    user: User = Depends(manager),
    db: Session = Depends(get_db),
):
    total, rows = coupon_service.list_coupons(
        db, user, page.skip, page.limit, restaurant_id, is_active, discount_type
    )
    return Page(total=total, skip=page.skip, limit=page.limit, items=[CouponOut.model_validate(c) for c in rows])


# Fixed path declared before "/{coupon_id}" routes.
@router.get("/available", response_model=Page[CouponPreviewOut])
def available(
    restaurant_id: Optional[int] = Query(None, description="Defaults to the restaurant in your cart"),
    page: PageParams = Depends(pagination),
    customer: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Usable coupons with an eligibility preview and discount for the current cart."""
    total, items = coupon_service.available_coupons(db, customer, page.skip, page.limit, restaurant_id)
    return Page(total=total, skip=page.skip, limit=page.limit, items=items)


@router.put("/{coupon_id}", response_model=CouponOut)
def update_coupon(coupon_id: int, data: CouponUpdate, user: User = Depends(manager), db: Session = Depends(get_db)):
    return coupon_service.update_coupon(db, user, coupon_id, data)


@router.put("/{coupon_id}/deactivate", response_model=CouponOut)
def deactivate(coupon_id: int, user: User = Depends(manager), db: Session = Depends(get_db)):
    return coupon_service.deactivate_coupon(db, user, coupon_id)
