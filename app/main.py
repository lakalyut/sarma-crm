import os
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.status import HTTP_302_FOUND

from .auth_deps import get_current_user
from .auth_routes import router as auth_router
from .database import Base, SessionLocal, engine
from .routes.admin_users import router as admin_users_router
from .routes.analytics import router as analytics_router
from .routes.imports import router as imports_router
from .routes.misc import router as misc_router
from .routes.products import router as products_router
from .startup import ensure_admin
from .templating import templates

load_dotenv()

AUTO_CREATE_SCHEMA = os.getenv("AUTO_CREATE_SCHEMA", "0") == "1"
if AUTO_CREATE_SCHEMA:
    Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        ensure_admin(db)
    finally:
        db.close()
    yield

app = FastAPI(title="Sarma CRM", lifespan=lifespan)

app.include_router(auth_router)
app.include_router(admin_users_router)
app.include_router(misc_router)
app.include_router(products_router)
app.include_router(imports_router)
app.include_router(analytics_router)

def render(request: Request, template_name: str, context: dict[str, Any]):
    db = SessionLocal()
    try:
        user = get_current_user(request, db)
    finally:
        db.close()

    ctx = {"request": request, **context, "current_user": user}
    return templates.TemplateResponse(template_name, ctx)


@app.exception_handler(401)
def _unauth(request: Request, exc):
    return RedirectResponse("/auth/login", status_code=HTTP_302_FOUND)


@app.exception_handler(403)
def _forbidden(request: Request, exc):
    db = SessionLocal()
    try:
        user = get_current_user(request, db)
    finally:
        db.close()

    return templates.TemplateResponse(
        "errors/403.html",
        {
            "request": request,
            "current_user": user,
        },
        status_code=403,
    )

@app.exception_handler(404)
def not_found_handler(request: Request, exc):
    db = SessionLocal()
    try:
        user = get_current_user(request, db)
    finally:
        db.close()

    return templates.TemplateResponse(
        "errors/404.html",
        {
            "request": request,
            "current_user": user,
        },
        status_code=404,
    )

@app.exception_handler(Exception)
def server_error_handler(request: Request, exc):
    db = SessionLocal()
    try:
        user = get_current_user(request, db)
    finally:
        db.close()

    return templates.TemplateResponse(
        "errors/500.html",
        {
            "request": request,
            "current_user": user,
        },
        status_code=500,
    )

