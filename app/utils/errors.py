"""Application exceptions and consistent error-response helpers."""
from typing import Any, Optional


class AppError(Exception):
    """Base class for expected, user-facing errors.

    The global exception handler converts it to a JSON body of the form
    ``{"success": false, "error": {"status_code": ..., "message": ..., "details": ...}}``.
    """

    status_code: int = 400

    def __init__(self, message: str, status_code: Optional[int] = None, details: Any = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.details = details


class BadRequestError(AppError):
    status_code = 400


class UnauthorizedError(AppError):
    status_code = 401


class ForbiddenError(AppError):
    status_code = 403


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


def error_body(status_code: int, message: str, details: Any = None) -> dict:
    """Build the standard error payload."""
    return {
        "success": False,
        "error": {"status_code": status_code, "message": message, "details": details},
    }
