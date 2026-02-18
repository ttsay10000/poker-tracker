"""Admin auth: shared password via env. Cookie or form-based."""
import secrets
from typing import Optional

from fastapi import Depends, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.security import APIKeyCookie

from config import ADMIN_PASSWORD, SECRET_KEY

COOKIE_NAME = "poker_admin"
# Simple signed token: not cryptographically strong but enough for home game
def _make_token() -> str:
    return secrets.token_urlsafe(32)


def _token_valid(token: str) -> bool:
    if not token or not ADMIN_PASSWORD:
        return False
    # We store "password_hash" as cookie value; for simplicity we store a signed token
    # and keep server-side session. Simpler: cookie value = sign(password) so we can verify without DB.
    # Simplest: cookie = token, and we store token in... we don't have Redis. So: cookie = HMAC(password).
    try:
        import hmac
        import hashlib
        expected = hmac.new(SECRET_KEY.encode(), ADMIN_PASSWORD.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(token, expected)
    except Exception:
        return False


def _get_signed_password_cookie() -> str:
    import hmac
    import hashlib
    return hmac.new(SECRET_KEY.encode(), ADMIN_PASSWORD.encode(), hashlib.sha256).hexdigest()


def set_admin_cookie(response: Response) -> None:
    """Set cookie after successful password check."""
    response.set_cookie(
        COOKIE_NAME,
        _get_signed_password_cookie(),
        httponly=True,
        samesite="lax",
        max_age=86400 * 30,
    )


def clear_admin_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME)


def get_admin_cookie(request: Request) -> Optional[str]:
    return request.cookies.get(COOKIE_NAME)


def require_admin(request: Request) -> bool:
    """Return True if request has valid admin cookie."""
    token = get_admin_cookie(request)
    return _token_valid(token) if token else False


def admin_depends(request: Request):
    """Dependency: redirect to login if not admin."""
    if require_admin(request):
        return True
    return RedirectResponse(url="/login", status_code=302)
