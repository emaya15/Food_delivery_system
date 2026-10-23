"""Order placement (Level 7), restaurant handling (Level 8) and ratings (Level 12)."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_current_user,
    pagination,
    require_approved_owner,
    require_customer,
    require_owner,
)
from app.enums import OrderStatus
from app.models.user import User
from app.schemas.common import Page
from app.schemas.delivery import RatingCreate, RatingOut, RestaurantRatingsOut
from app.schemas.order import (
    AcceptRequest,
    CancelRequest,
    OrderCreate,
    OrderOut,
    RejectRequest,
    ReorderOut,
)
from app.services import order_service, rating_service
from app.utils.errors import BadRequestError
from app.utils.pagination import PageParams

router = APIRouter(tags=["Orders"])


def _filters(
    status_: Optional[OrderStatus] = Query(None, alias="status"),
    restaurant_id: Optional[int] = None,
    from_date: Optional[date] = Query(None, description="Placed on/after (local date)"),
    to_date: Optional[date] = Query(None, description="Placed on/before (local date)"),
):
    if from_date and to_date and to_date < from_date:
        raise BadRequestError("to_date must not be before from_date")
    return status_, restaurant_id, from_date, to_date


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def place_order(data: OrderCreate, customer: User = Depends(require_customer), db: Session = Depends(get_db)):
    """Place an order from the cart (single atomic transaction)."""
    order = order_service.place_order(db, customer, data)
    return order_service.build_order_out(order, customer)


@router.get("/orders", response_model=Page[OrderOut])
def list_orders(
    f=Depends(_filters),
    page: PageParams = Depends(pagination),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Orders visible to the caller, filterable by status, restaurant and date range."""
    total, rows = order_service.list_orders(db, user, page.skip, page.limit, *f)
    return Page(total=total, skip=page.skip, limit=page.limit, items=[order_service.build_order_out(o, user) for o in rows])


@router.get("/restaurants/me/orders", response_model=Page[OrderOut], tags=["Restaurant Orders"])
def restaurant_orders(
    status_: Optional[OrderStatus] = Query(None, alias="status"),
    restaurant_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    page: PageParams = Depends(pagination),
    owner: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    total, rows = order_service.list_orders(db, owner, page.skip, page.limit, status_, restaurant_id, from_date, to_date)
    return Page(total=total, skip=page.skip, limit=page.limit, items=[order_service.build_order_out(o, owner) for o in rows])


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = order_service.get_order_for_user(db, user, order_id)
    return order_service.build_order_out(order, user)


@router.put("/orders/{order_id}/cancel", response_model=OrderOut)
def cancel(
    order_id: int,
    body: Optional[CancelRequest] = None,
    customer: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    order = order_service.cancel_order(db, customer, order_id, body.reason if body else None)
    return order_service.build_order_out(order, customer)


@router.post("/orders/{order_id}/reorder", response_model=ReorderOut, status_code=status.HTTP_201_CREATED)
def reorder(order_id: int, customer: User = Depends(require_customer), db: Session = Depends(get_db)):
    return order_service.reorder(db, customer, order_id)


@router.put("/orders/{order_id}/accept", response_model=OrderOut, tags=["Restaurant Orders"])
def accept(order_id: int, data: AcceptRequest, owner: User = Depends(require_approved_owner), db: Session = Depends(get_db)):
    order = order_service.accept_order(db, owner, order_id, data.preparation_minutes)
    return order_service.build_order_out(order, owner)


@router.put("/orders/{order_id}/reject", response_model=OrderOut, tags=["Restaurant Orders"])
def reject(order_id: int, data: RejectRequest, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    order = order_service.reject_order(db, owner, order_id, data.reason)
    return order_service.build_order_out(order, owner)


@router.put("/orders/{order_id}/preparing", response_model=OrderOut, tags=["Restaurant Orders"])
def preparing(order_id: int, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return order_service.build_order_out(order_service.mark_preparing(db, owner, order_id), owner)


@router.put("/orders/{order_id}/ready", response_model=OrderOut, tags=["Restaurant Orders"])
def ready(order_id: int, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return order_service.build_order_out(order_service.mark_ready(db, owner, order_id), owner)


# ------------------------------------------------------------------ ratings
@router.post("/orders/{order_id}/rating", response_model=RatingOut, status_code=status.HTTP_201_CREATED, tags=["Ratings"])
def rate_order(order_id: int, data: RatingCreate, customer: User = Depends(require_customer), db: Session = Depends(get_db)):
    return rating_service.create_rating(db, customer, order_id, data)


@router.get("/restaurants/{restaurant_id}/ratings", response_model=RestaurantRatingsOut, tags=["Ratings"])
def restaurant_ratings(
    restaurant_id: int,
    page: PageParams = Depends(pagination),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return rating_service.list_restaurant_ratings(db, restaurant_id, page.skip, page.limit)
