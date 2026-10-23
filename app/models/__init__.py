"""Import every model so that ``Base.metadata`` is fully populated (Alembic relies on this)."""
from app.models.address import Address
from app.models.cart import Cart, CartItem
from app.models.coupon import Coupon, CouponUsage
from app.models.delivery import AdminNotification, DeliveryOffer, Rating
from app.models.order import Order, OrderItem, OrderSequence, OrderStatusHistory
from app.models.restaurant import MenuCategory, MenuItem, Restaurant
from app.models.user import DeliveryPartnerProfile, User

__all__ = [
    "Address",
    "AdminNotification",
    "Cart",
    "CartItem",
    "Coupon",
    "CouponUsage",
    "DeliveryOffer",
    "DeliveryPartnerProfile",
    "MenuCategory",
    "MenuItem",
    "Order",
    "OrderItem",
    "OrderSequence",
    "OrderStatusHistory",
    "Rating",
    "Restaurant",
    "User",
]
