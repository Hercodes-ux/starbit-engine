"""
Login state lives entirely in Starlette's signed session cookie
(itsdangerous-signed, tamper-proof, set via `request.session`) --
NOT in a server-side dict. This is deliberate: a dict in process
memory is wiped every time uvicorn --reload restarts (which happens
on every file save during development), silently logging everyone
out mid-demo. The cookie survives restarts because it lives in the
browser, not the server.

The one thing that genuinely CANNOT survive a restart is the actual
loaded dataset (an in-memory DuckDB connection -- see database.py).
We handle that gracefully in chat_routes.py rather than pretending
it's a login problem.
"""
import uuid
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, JSONResponse

from auth import oauth, get_mock_user
from config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


def _log_in_session(request: Request, email: str, name: str, picture: str | None):
    request.session["user_email"] = email
    request.session["user_name"] = name
    request.session["user_picture"] = picture
    request.session["dataset_key"] = uuid.uuid4().hex  # keys the DuckDB connection in database.py
    request.session["has_dataset"] = False
    request.session["dataset_name"] = None
    request.session["questions_used"] = 0


@router.get("/login")
async def login(request: Request):
    if settings.mock_auth:
        # Dev/demo shortcut: skip the real Google redirect and log in
        # as a fake user instantly. Set MOCK_AUTH=false in .env for the
        # real Google account picker.
        user = get_mock_user()
        _log_in_session(request, user["email"], user["name"], user["picture"])
        return RedirectResponse(url=f"{settings.frontend_origin}/index.html?logged_in=1")

    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def auth_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo") or {}
    _log_in_session(
        request,
        userinfo.get("email", "unknown@starbit.dev"),
        userinfo.get("name", "Traveler"),
        userinfo.get("picture"),
    )
    return RedirectResponse(url=f"{settings.frontend_origin}/index.html?logged_in=1")


@router.get("/me")
async def me(request: Request):
    email = request.session.get("user_email")
    if not email:
        return JSONResponse({"logged_in": False})
    questions_used = request.session.get("questions_used", 0)
    return JSONResponse({
        "logged_in": True,
        "name": request.session.get("user_name"),
        "email": email,
        "picture": request.session.get("user_picture"),
        "has_dataset": request.session.get("has_dataset", False),
        "questions_remaining": max(0, settings.max_questions_per_session - questions_used),
    })


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return JSONResponse({"ok": True})
