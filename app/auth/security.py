"""Password hashing and JWT helpers."""
from datetime import timedelta
from typing import Any, Dict, Optional

import jwt
from passlib.context import CryptContext

from app.config import get_settings
from app.utils.errors import UnauthorizedError
from app.utils.timeutils import utcnow

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time password verification; returns False for malformed hashes."""
    try:
        return _pwd_context.verify(password, password_hash)
    except (ValueError, TypeError):
        return False


def create_access_token(subject: int, extra: Optional[Dict[str, Any]] = None,
                        expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT. Default lifetime is ``ACCESS_TOKEN_EXPIRE_MINUTES`` (30)."""
    settings = get_settings()
    now = utcnow()
    expire = now + (expires_delta if expires_delta is not None else timedelta(minutes=settings.access_token_expire_minutes))
    payload: Dict[str, Any] = {"sub": str(subject), "iat": now, "exp": expire}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT; raises ``UnauthorizedError`` (HTTP 401) if invalid/expired."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Token has expired") from None
    except jwt.InvalidTokenError:
        raise UnauthorizedError("Invalid authentication token") from None
    if "sub" not in payload:
        raise UnauthorizedError("Invalid authentication token")
    return payload
