"""Timezone strategy.

* Every timestamp is stored in the database in **UTC** (see ``UTCDateTime``).
* Business rules that depend on the wall clock (restaurant opening hours,
  surge pricing, "today" in reports) use the configured local timezone
  (``TIMEZONE`` setting, default ``Asia/Kolkata``).
"""
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from app.config import get_settings


def utcnow() -> datetime:
    """Current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


@lru_cache
def local_tz() -> ZoneInfo:
    """Configured business timezone."""
    return ZoneInfo(get_settings().timezone)


def ensure_aware(value: datetime) -> datetime:
    """Treat naive datetimes as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def to_local(value: datetime) -> datetime:
    """Convert a datetime to the business timezone."""
    return ensure_aware(value).astimezone(local_tz())


def local_now() -> datetime:
    """Current time in the business timezone."""
    return utcnow().astimezone(local_tz())


def local_today() -> date:
    """Today's date in the business timezone."""
    return local_now().date()


def local_day_bounds_utc(day: date) -> "tuple[datetime, datetime]":
    """UTC [start, end) bounds of a local calendar day."""
    start_local = datetime.combine(day, time.min, tzinfo=local_tz())
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def local_range_bounds_utc(start: date, end: date) -> "tuple[datetime, datetime]":
    """UTC [start, end) bounds covering local days ``start`` .. ``end`` inclusive."""
    return local_day_bounds_utc(start)[0], local_day_bounds_utc(end)[1]
