"""Cart endpoints (Level 5) and coupon application (Level 6)."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_customer
from app.models.user import User
from app.schemas.cart import ApplyCouponRequest, CartItemAdd, CartItemUpdate, CartOut
from app.services import cart_service

router = APIRouter(tags=["Cart"])


@router.get("/cart", response_model=CartOut)
def view_cart(customer: User = Depends(require_customer), db: Session = Depends(get_db)):
    return cart_service.view_cart(db, customer)


@router.post("/cart/items", response_model=CartOut, status_code=status.HTTP_201_CREATED)
def add_item(data: CartItemAdd, customer: User = Depends(require_customer), db: Session = Depends(get_db)):
    """Add an item; adding the same item again increases its quantity. 409 for a different restaurant."""
    return cart_service.add_item(db, customer, data)


@router.put("/cart/items/{item_id}", response_model=CartOut)
def update_item(
    item_id: int, data: CartItemUpdate, customer: User = Depends(require_customer), db: Session = Depends(get_db)
):
    return cart_service.update_item(db, customer, item_id, data)


@router.delete("/cart/items/{item_id}", response_model=CartOut)
def remove_item(item_id: int, customer: User = Depends(require_customer), db: Session = Depends(get_db)):
    return cart_service.remove_item(db, customer, item_id)


@router.delete("/cart", response_model=CartOut)
def clear_cart(customer: User = Depends(require_customer), db: Session = Depends(get_db)):
    """Empty the cart and clear any applied coupon."""
    return cart_service.clear_cart(db, customer)


@router.post("/cart/apply-coupon", response_model=CartOut)
def apply_coupon(data: ApplyCouponRequest, customer: User = Depends(require_customer), db: Session = Depends(get_db)):
    return cart_service.apply_coupon(db, customer, data)


@router.delete("/cart/coupon", response_model=CartOut)
def remove_coupon(customer: User = Depends(require_customer), db: Session = Depends(get_db)):
    return cart_service.remove_coupon(db, customer)
