"""Enumerations shared by models, schemas and services.

Enums are persisted as plain ``VARCHAR`` columns (not native DB enums) so that
adding a value never requires an ``ALTER TABLE`` on a large table.
"""
import enum


class Role(str, enum.Enum):
    ADMIN = "Admin"
    RESTAURANT_OWNER = "Restaurant Owner"
    DELIVERY_PARTNER = "Delivery Partner"
    CUSTOMER = "Customer"


class OrderStatus(str, enum.Enum):
    PLACED = "Placed"
    ACCEPTED = "Accepted"
    PREPARING = "Preparing"
    READY_FOR_PICKUP = "Ready for Pickup"
    PICKED_UP = "Picked Up"
    OUT_FOR_DELIVERY = "Out for Delivery"
    DELIVERED = "Delivered"
    CANCELLED = "Cancelled"
    REJECTED = "Rejected"


# Statuses in which a delivery partner is considered "busy" with the order.
ACTIVE_DELIVERY_STATUSES = (
    OrderStatus.ACCEPTED,
    OrderStatus.PREPARING,
    OrderStatus.READY_FOR_PICKUP,
    OrderStatus.PICKED_UP,
    OrderStatus.OUT_FOR_DELIVERY,
)

# Orders that need a delivery partner assigned.
ASSIGNABLE_STATUSES = (
    OrderStatus.ACCEPTED,
    OrderStatus.PREPARING,
    OrderStatus.READY_FOR_PICKUP,
)

TERMINAL_STATUSES = (OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.REJECTED)

# Allowed state machine transitions.
ALLOWED_TRANSITIONS = {
    OrderStatus.PLACED: {OrderStatus.ACCEPTED, OrderStatus.REJECTED, OrderStatus.CANCELLED},
    OrderStatus.ACCEPTED: {OrderStatus.PREPARING},
    OrderStatus.PREPARING: {OrderStatus.READY_FOR_PICKUP},
    OrderStatus.READY_FOR_PICKUP: {OrderStatus.PICKED_UP},
    OrderStatus.PICKED_UP: {OrderStatus.OUT_FOR_DELIVERY},
    OrderStatus.OUT_FOR_DELIVERY: {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.REJECTED: set(),
}


class PaymentMethod(str, enum.Enum):
    COD = "COD"
    ONLINE = "ONLINE"


class PaymentStatus(str, enum.Enum):
    PENDING = "Pending"
    PAID = "Paid"
    REFUNDED = "Refunded"


class DiscountType(str, enum.Enum):
    PERCENTAGE = "PERCENTAGE"
    FLAT = "FLAT"


class OfferStatus(str, enum.Enum):
    PENDING = "Pending"
    ACCEPTED = "Accepted"
    DECLINED = "Declined"
    EXPIRED = "Expired"
