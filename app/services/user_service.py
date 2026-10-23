"""User registration, authentication, approval and admin bootstrap."""
from typing import Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.security import create_access_token, hash_password, verify_password
from app.config import get_settings
from app.database import transaction
from app.enums import Role
from app.models.user import DeliveryPartnerProfile, User
from app.schemas.auth import RegisterRequest
from app.utils.errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError, UnauthorizedError

_dummy_hash: Optional[str] = None


def _get_dummy_hash() -> str:
    """Hash used to equalise timing when an email does not exist."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("not-a-real-password-1")
    return _dummy_hash


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.scalar(select(User).where(func.lower(User.email) == email.lower()))


def register_user(db: Session, data: RegisterRequest) -> User:
    """Create a Customer, Restaurant Owner or Delivery Partner account.

    Admin accounts can never be registered publicly (HTTP 403).
    Owners and partners start unapproved; customers are approved immediately.
    """
    if data.role == Role.ADMIN:
        raise ForbiddenError("Admin accounts cannot be created through public registration")
    if get_user_by_email(db, data.email):
        raise ConflictError("Email is already registered")
    if data.role == Role.DELIVERY_PARTNER:
        exists = db.scalar(
            select(DeliveryPartnerProfile.id).where(DeliveryPartnerProfile.vehicle_number == data.vehicle_number)
        )
        if exists:
            raise ConflictError("Vehicle number is already registered")

    try:
        with transaction(db):
            user = User(
                name=data.name,
                email=data.email,
                phone=data.phone,
                password_hash=hash_password(data.password),
                role=data.role.value,
                is_active=True,
                is_approved=data.role == Role.CUSTOMER,
            )
            if data.role == Role.DELIVERY_PARTNER:
                user.partner_profile = DeliveryPartnerProfile(
                    vehicle_number=data.vehicle_number, vehicle_type=data.vehicle_type, is_online=False
                )
            db.add(user)
            db.flush()
    except IntegrityError:
        raise ConflictError("Email or vehicle number is already registered") from None
    return user


def authenticate(db: Session, email: str, password: str) -> Tuple[User, str, int]:
    """Validate credentials and return ``(user, access_token, expires_in_seconds)``."""
    user = get_user_by_email(db, email)
    if user is None:
        verify_password(password, _get_dummy_hash())
        raise UnauthorizedError("Incorrect email or password")
    if not verify_password(password, user.password_hash):
        raise UnauthorizedError("Incorrect email or password")
    if not user.is_active:
        raise ForbiddenError("Account is inactive")
    settings = get_settings()
    token = create_access_token(user.id, {"role": user.role})
    return user, token, settings.access_token_expire_minutes * 60


def set_approval(db: Session, user_id: int, approved: bool = True) -> User:
    """Approve (or revoke approval of) a Restaurant Owner / Delivery Partner."""
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    if user.role not in (Role.RESTAURANT_OWNER.value, Role.DELIVERY_PARTNER.value):
        raise BadRequestError("Only Restaurant Owners and Delivery Partners require approval")
    with transaction(db):
        user.is_approved = approved
        if not approved and user.partner_profile is not None:
            user.partner_profile.is_online = False
        db.flush()
    return user


def list_users(db: Session, skip: int, limit: int, role: Optional[str] = None, is_approved: Optional[bool] = None):
    """Admin listing of users with optional filters."""
    stmt = select(User)
    count_stmt = select(func.count(User.id))
    if role:
        stmt = stmt.where(User.role == role)
        count_stmt = count_stmt.where(User.role == role)
    if is_approved is not None:
        stmt = stmt.where(User.is_approved.is_(is_approved))
        count_stmt = count_stmt.where(User.is_approved.is_(is_approved))
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(User.id).offset(skip).limit(limit)).all()
    return total, rows


def create_admin(db: Session, name: str, email: str, phone: str, password: str) -> User:
    """Create an Admin account (used only by the ``create-admin`` CLI command)."""
    email = email.strip().lower()
    if get_user_by_email(db, email):
        raise ConflictError("A user with this email already exists")
    if len(password) < 8 or len(password) > 72:
        raise BadRequestError("Password must be 8-72 characters")
    if not phone.isdigit() or len(phone) != 10:
        raise BadRequestError("Phone must be exactly 10 digits")
    with transaction(db):
        user = User(
            name=name.strip(),
            email=email,
            phone=phone,
            password_hash=hash_password(password),
            role=Role.ADMIN.value,
            is_active=True,
            is_approved=True,
        )
        db.add(user)
        db.flush()
    return user
