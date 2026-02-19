"""Shared Jinja2 templates with currency filter (+$ / -$)."""
from fastapi.templating import Jinja2Templates

from config import BASE_DIR


def _signed_dollars(value):
    """Format number as +$X,XXX.XX or -$X,XXX.XX. None -> —."""
    if value is None:
        return "—"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if n >= 0 else "-"
    return sign + "${:,.2f}".format(abs(n))


def get_templates():
    t = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    t.env.filters["signed_dollars"] = _signed_dollars
    return t


templates = get_templates()
