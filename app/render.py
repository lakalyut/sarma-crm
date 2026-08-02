from fastapi import Request
from starlette.responses import Response

from .auth_deps import get_current_user
from .csrf import attach_csrf_cookie, get_csrf_token
from .database import SessionLocal
from .services.event_log_service import count_unread_events
from .templating import templates


def render(request: Request, template_name: str, context: dict) -> Response:
    db = SessionLocal()
    try:
        user = get_current_user(request, db)
        unread_events = count_unread_events(db, user)
    finally:
        db.close()

    csrf_token = get_csrf_token(request)

    ctx = {
        "request": request,
        "current_user": user,
        "unread_events": unread_events,
        "csrf_token": csrf_token,
        **context,
    }
    response = templates.TemplateResponse(template_name, ctx)
    attach_csrf_cookie(response, request, csrf_token)
    return response
