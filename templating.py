"""Shared Jinja2 templates with currency filter (+$ / -$)."""
from typing import Any

from fastapi.templating import Jinja2Templates

from config import BASE_DIR


class CompatJinja2Templates(Jinja2Templates):
    """Bridge Starlette's old and new TemplateResponse signatures.

    Older code in this app uses:
      templates.TemplateResponse("page.html", {"request": request, ...})

    Starlette 1.0 removes that deprecated form and requires:
      templates.TemplateResponse(request, "page.html", {...})

    Converting centrally here keeps the routers simple and compatible across
    both runtime families.
    """

    def TemplateResponse(self, *args: Any, **kwargs: Any):
        if args and isinstance(args[0], str):
            name = args[0]
            context = args[1] if len(args) > 1 else kwargs.pop("context", {})
            if "request" not in context:
                raise ValueError('context must include a "request" key')
            request = context["request"]
            return super().TemplateResponse(request, name, context, *args[2:], **kwargs)

        if not args and "name" in kwargs and "request" not in kwargs and "context" in kwargs:
            context = kwargs.get("context") or {}
            request = context.get("request")
            if request is not None:
                kwargs = dict(kwargs)
                kwargs["request"] = request

        return super().TemplateResponse(*args, **kwargs)


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


def _abs_dollars(value):
    """Format number as $X,XXX.XX (magnitude only). None -> —."""
    if value is None:
        return "—"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    return "${:,.2f}".format(abs(n))


def get_templates():
    t = CompatJinja2Templates(directory=str(BASE_DIR / "templates"))
    t.env.filters["signed_dollars"] = _signed_dollars
    t.env.filters["abs_dollars"] = _abs_dollars
    return t


templates = get_templates()
