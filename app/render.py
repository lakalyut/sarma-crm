from fastapi import Request
from starlette.responses import Response

from .auth_deps import get_current_user
from .database import SessionLocal
from .templating import templates


def render(request: Request, template_name: str, context: dict) -> Response:
    db = SessionLocal()
    try:
        user = get_current_user(request, db)
    finally:
        db.close()

    ctx = {"request": request, "current_user": user, **context}
    return templates.TemplateResponse(template_name, ctx)
