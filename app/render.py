from fastapi import Request
from starlette.responses import Response

from .auth_deps import get_current_user
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

    ctx = {
        "request": request,
        "current_user": user,
        "unread_events": unread_events,
        **context,
    }
    return templates.TemplateResponse(template_name, ctx)
