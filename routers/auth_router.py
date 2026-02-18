"""Login / logout."""
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from auth import clear_admin_cookie, require_admin, set_admin_cookie
from config import BASE_DIR

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/login")
async def login_page(request: Request):
    if require_admin(request):
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login_post(request: Request):
    form = await request.form()
    password = form.get("password", "")
    from config import ADMIN_PASSWORD
    if password and password == ADMIN_PASSWORD:
        response = RedirectResponse(url="/dashboard", status_code=302)
        set_admin_cookie(response)
        return response
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Invalid password"},
    )


@router.get("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=302)
    clear_admin_cookie(response)
    return response
