"""Common schema building blocks."""
import re
from decimal import Decimal
from typing import Annotated, Generic, List, TypeVar

from pydantic import BaseModel, ConfigDict, PlainSerializer

T = TypeVar("T")

# Money is computed with Decimal and serialised to JSON as a plain number.
Money = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]

PHONE_PATTERN = re.compile(r"^\d{10}$")
PINCODE_PATTERN = re.compile(r"^\d{6}$")
EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


class ORMModel(BaseModel):
    """Base class for response models built from SQLAlchemy objects."""

    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    """Standard paginated list envelope."""

    total: int
    skip: int
    limit: int
    items: List[T]


class MessageOut(BaseModel):
    """Simple message response."""

    message: str


def validate_phone(value: str) -> str:
    """Ensure a ten-digit phone number."""
    if not PHONE_PATTERN.match(value):
        raise ValueError("phone must be exactly 10 digits")
    return value


def validate_pincode(value: str) -> str:
    """Ensure a six-digit pincode."""
    if not PINCODE_PATTERN.match(value):
        raise ValueError("pincode must be exactly 6 digits")
    return value
