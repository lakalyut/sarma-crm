from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..auth_deps import require_user
from ..auth_models import User
from ..database import get_db
from ..render import render
from ..services.event_log_service import (
    list_events,
    mark_events_seen,
    relative_day_label,
)
from ..services.sales_options_service import get_cities
from ..templating import format_month_list

router = APIRouter()


@router.get("/events")
def event_log_page(
    request: Request,
    city: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    mark_events_seen(db, user)

    cities = get_cities(db)

    events = [
        {
            "day_label": relative_day_label(e.created_at),
            "time_label": e.created_at.strftime("%H:%M"),
            "user_email": e.user.email if e.user else "—",
            "city": e.city,
            "months_display": (
                format_month_list(e.months.split(", ")) if e.months else ""
            ),
            "rows_imported": e.rows_imported,
            "rows_unmatched": e.rows_unmatched,
        }
        for e in list_events(db, city=city or None)
    ]

    return render(
        request,
        "events/event_log.html",
        {
            "title": "Лента — Пульс",
            "cities": cities,
            "selected_city": city,
            "events": events,
            "empty_state": {
                "title": "Событий пока нет",
                "hint": "Здесь появится история импортов, как только кто-то загрузит данные.",
            },
        },
    )
