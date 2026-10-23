"""Reusable FastAPI dependencies: authentication, authorisation and pagination."""
from typing import Callable

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.database import get_db
from app.enums import Role
from app.models.user import User
from app.utils.constants import DEFAULT_LIMIT, MAX_LIMIT
from app.utils.errors import ForbiddenError, UnauthorizedError
from app.utils.pagination import PageParams

bearer_scheme = HTTPBearer(auto_error=False, description="Paste the access token from POST /auth/login")


def user_from_token(db: Session, token: str) -> User:
    """Resolve a user from a JWT (shared by HTTP and WebSocket authentication)."""
    payload = decode_access_token(token)
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise UnauthorizedError("Invalid authentication token") from None
    user = db.get(User, user_id)
    if user is None:
        raise UnauthorizedError("Invalid authentication token")
    if not user.is_active:
        raise ForbiddenError("Account is inactive")
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Return the authenticated user or raise 401/403."""
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Not authenticated")
    return user_from_token(db, credentials.credentials)


def require_roles(*roles: Role) -> Callable[..., User]:
    """Dependency factory: user must hold one of ``roles`` (403 otherwise)."""

    allowed = {r.value for r in roles}

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise ForbiddenError("You do not have permission to perform this action")
        return user

    return checker


def require_approved_roles(*roles: Role) -> Callable[..., User]:
    """Like ``require_roles`` but additionally requires admin approval."""

    allowed = {r.value for r in roles}

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise ForbiddenError("You do not have permission to perform this action")
        if not user.is_approved:
            raise ForbiddenError("Your account is pending admin approval")
        return user

    return checker


require_admin = require_roles(Role.ADMIN)
require_customer = require_roles(Role.CUSTOMER)
require_owner = require_roles(Role.RESTAURANT_OWNER)
require_approved_owner = require_approved_roles(Role.RESTAURANT_OWNER)
require_partner = require_roles(Role.DELIVERY_PARTNER)
require_approved_partner = require_approved_roles(Role.DELIVERY_PARTNER)


def pagination(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Maximum records to return"),
) -> PageParams:
    """Validated ``skip`` / ``limit`` query parameters."""
    return PageParams(skip=skip, limit=limit)
