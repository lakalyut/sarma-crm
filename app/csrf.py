import secrets

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

CSRF_COOKIE_NAME = "csrf_token"
CSRF_COOKIE_MAX_AGE = 60 * 60 * 24 * 14
CSRF_METHODS = ("POST", "PUT", "PATCH", "DELETE")


def get_csrf_token(request: Request) -> str:
    return request.cookies.get(CSRF_COOKIE_NAME) or secrets.token_urlsafe(32)


def attach_csrf_cookie(response: Response, request: Request, token: str) -> None:
    if request.cookies.get(CSRF_COOKIE_NAME):
        return

    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=CSRF_COOKIE_MAX_AGE,
        path="/",
    )


def verify_csrf(cookie_token: str | None, form_token: str | None) -> bool:
    if not cookie_token or not form_token:
        return False
    # compare_digest требует bytes или ASCII-only str — токен из формы может
    # быть чем угодно (подделанный/битый cookie), сравниваем как bytes, чтобы
    # не словить TypeError вместо честного "не совпало".
    return secrets.compare_digest(
        cookie_token.encode("utf-8"), form_token.encode("utf-8")
    )


async def csrf_guard(request: Request) -> None:
    """Зависимость уровня приложения (FastAPI(dependencies=[...])), а не
    @app.middleware("http") — в Starlette 0.37 BaseHTTPMiddleware не реплеит
    тело запроса корректно для повторного request.form() у самого роута
    (проверено эмпирически: мидлварь видит поля формы, роут получает пустые
    значения). Зависимость работает с тем же объектом Request, что и Form(...)
    у роута — request.form() кеширует результат, повторное чтение безопасно."""
    if request.method not in CSRF_METHODS:
        return

    try:
        form = await request.form()
    except Exception:
        form = None

    form_token = form.get(CSRF_COOKIE_NAME) if form else None
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)

    if not verify_csrf(cookie_token, form_token):
        raise HTTPException(status_code=403)
