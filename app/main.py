import os
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.status import HTTP_302_FOUND

from .auth_deps import get_current_user
from .auth_routes import router as auth_router
from .csrf import attach_csrf_cookie, csrf_guard, get_csrf_token
from .database import Base, SessionLocal, engine
from .routes.admin_abc import router as admin_abc_router
from .routes.admin_imports import router as admin_imports_router
from .routes.admin_regions import router as admin_regions_router
from .routes.admin_users import router as admin_users_router
from .routes.ambassador_app import router as ambassador_app_router
from .routes.ambassador_web import router as ambassador_web_router
from .routes.analytics import router as analytics_router
from .routes.client_analysis import router as client_analysis_router
from .routes.dashboard import router as dashboard_router
from .routes.events import router as events_router
from .routes.imports import router as imports_router
from .routes.leaderboard import router as leaderboard_router
from .routes.misc import router as misc_router
from .routes.products import router as products_router
from .routes.telegram_bot import router as telegram_bot_router
from .routes.telegram_poc import router as telegram_poc_router
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


app = FastAPI(title="Пульс", lifespan=lifespan, dependencies=[Depends(csrf_guard)])

# Большие аналитические страницы (напр. «Клиенты» на крупном городе — тысячи
# строк таблицы) отдают HTML в единицы МБ из-за повторяющейся разметки/атрибутов
# на каждой строке; такой текст сжимается gzip'ом в 15-20 раз почти бесплатно по
# CPU — сильно сокращает время загрузки на реальном канале (заметно на localhost
# незначительно, но ощутимо на бою). min_size — не сжимать мелкие ответы (JSON API,
# небольшие страницы), там оверхед gzip-заголовка не окупается.
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(auth_router)
app.include_router(admin_users_router)
app.include_router(misc_router)
app.include_router(products_router)
app.include_router(imports_router)
app.include_router(analytics_router)
app.include_router(dashboard_router)
app.include_router(admin_imports_router)
app.include_router(client_analysis_router)
app.include_router(admin_abc_router)
app.include_router(admin_regions_router)
app.include_router(events_router)
app.include_router(leaderboard_router)
app.include_router(telegram_poc_router)
app.include_router(telegram_bot_router)
app.include_router(ambassador_app_router)
app.include_router(ambassador_web_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


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


def _render_error(request: Request, template_name: str, status_code: int):
    # Страницы ошибок несут тот же сайдбар/форму логаута, что и обычные
    # страницы (base.html) — им тоже нужен настоящий csrf_token в контексте
    # и выставленная cookie, иначе csrf.js подставит в форму логаута пустое
    # значение, оно не совпадёт с cookie, и сам POST /auth/logout получит
    # свой собственный 403 — тупик без выхода со страницы ошибки (поймано
    # вживую: залогинен под ролью с урезанным доступом, любой 403 подряд).
    db = SessionLocal()
    try:
        user = get_current_user(request, db)
    finally:
        db.close()

    csrf_token = get_csrf_token(request)
    response = templates.TemplateResponse(
        template_name,
        {"request": request, "current_user": user, "csrf_token": csrf_token},
        status_code=status_code,
    )
    attach_csrf_cookie(response, request, csrf_token)
    return response


@app.exception_handler(403)
def _forbidden(request: Request, exc):
    return _render_error(request, "errors/403.html", 403)


@app.exception_handler(404)
def not_found_handler(request: Request, exc):
    return _render_error(request, "errors/404.html", 404)


@app.exception_handler(Exception)
def server_error_handler(request: Request, exc):
    return _render_error(request, "errors/500.html", 500)
