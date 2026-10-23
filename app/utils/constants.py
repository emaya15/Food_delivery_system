"""Business-rule constants for the Food Delivery System.

All monetary constants are expressed in Indian rupees (INR) and are stored as
``Decimal`` so that no floating point arithmetic is ever used for money.
"""
from decimal import Decimal

# --- Delivery fee --------------------------------------------------------
BASE_DELIVERY_FEE = Decimal("20.00")          # covers the first 3 km
BASE_DELIVERY_KM = Decimal("3")
EXTRA_DELIVERY_FEE_PER_KM = Decimal("8.00")   # per additional km (rounded up)
SURGE_MULTIPLIER = Decimal("1.5")
SURGE_WINDOWS = ((12, 14), (19, 22))          # local hours [start, end)

# --- Billing -------------------------------------------------------------
PLATFORM_FEE = Decimal("5.00")
GST_RATE = Decimal("0.05")

# --- Delivery partner earnings -------------------------------------------
PARTNER_BASE_EARNING = Decimal("25.00")
PARTNER_EARNING_PER_KM = Decimal("6.00")

# --- Travel / assignment -------------------------------------------------
TRAVEL_SPEED_KMPH = 20.0
PARTNER_SEARCH_RADIUS_KM = 5.0
OFFER_TTL_SECONDS = 30
MAX_OTP_ATTEMPTS = 3
UNASSIGNED_ADMIN_ALERT_MINUTES = 15
AUTO_REJECT_AFTER_MINUTES = 5
PARTNER_OFFLINE_AFTER_MINUTES = 10
AUTO_REJECT_REASON = "Restaurant did not respond"

# --- Cart ----------------------------------------------------------------
MIN_ITEM_QUANTITY = 1
MAX_ITEM_QUANTITY = 10
CART_CONFLICT_MESSAGE = "Your cart has items from another restaurant. Clear the cart to continue"

# --- Pagination ----------------------------------------------------------
DEFAULT_LIMIT = 20
MAX_LIMIT = 100

# --- Scheduled orders ----------------------------------------------------
MIN_SCHEDULE_LEAD_MINUTES = 30
