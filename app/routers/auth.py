"""Authentication and admin user-management endpoints (Level 2)."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, pagination, require_admin
from app.enums import Role
from app.models.user import User
from app.schemas.auth import ApprovalRequest, LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.schemas.common import Page
from app.schemas.delivery import NotificationOut
from app.services import notification_service, user_service
from app.utils.pagination import PageParams

router = APIRouter(tags=["Auth"])


@router.post("/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    """Register a Customer, Restaurant Owner or Delivery Partner (Admin is not allowed)."""
    return user_service.register_user(db, data)


@router.post("/auth/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    """Exchange email + password for a 30-minute JWT access token."""
    user, token, expires_in = user_service.authenticate(db, data.email, data.password)
    return TokenResponse(access_token=token, expires_in=expires_in, user=UserOut.model_validate(user))


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    """Profile of the authenticated user."""
    return user


@router.put("/admin/users/{user_id}/approve", response_model=UserOut, tags=["Admin"])
def approve_user(
    user_id: int,
    body: Optional[ApprovalRequest] = None,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Approve a Restaurant Owner or Delivery Partner (send ``{"approved": false}`` to revoke)."""
    return user_service.set_approval(db, user_id, body.approved if body else True)


@router.get("/admin/users", response_model=Page[UserOut], tags=["Admin"])
def list_users(
    role: Optional[Role] = None,
    is_approved: Optional[bool] = None,
    page: PageParams = Depends(pagination),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List users (Admin only), e.g. ``?role=Restaurant Owner&is_approved=false`` for pending approvals."""
    total, rows = user_service.list_users(db, page.skip, page.limit, role.value if role else None, is_approved)
    return Page(total=total, skip=page.skip, limit=page.limit, items=[UserOut.model_validate(u) for u in rows])


@router.get("/admin/notifications", response_model=Page[NotificationOut], tags=["Admin"])
def admin_notifications(
    unread_only: bool = False,
    page: PageParams = Depends(pagination),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Persisted admin alerts (unassigned orders, locked OTPs)."""
    total, rows = notification_service.list_admin_notifications(db, page.skip, page.limit, unread_only)
    return Page(total=total, skip=page.skip, limit=page.limit, items=[NotificationOut.model_validate(n) for n in rows])
