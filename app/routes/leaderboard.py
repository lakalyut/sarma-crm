from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ..auth_deps import require_analyst
from ..auth_models import User
from ..database import get_db
from ..render import render
from ..services.leaderboard_service import get_leaderboard, get_leaderboard_months

router = APIRouter()


@router.get("/leaderboard")
def leaderboard_page(
    request: Request,
    months: list[str] = Query(default=None),
    db: Session = Depends(get_db),
    _user: User = Depends(require_analyst),
):
    all_months = get_leaderboard_months(db)
    selected_months = [m for m in (months or []) if m in all_months]

    return render(
        request,
        "leaderboard/leaderboard.html",
        {
            "title": "Лидерборд — Пульс",
            "all_months": all_months,
            "selected_months": selected_months,
            "rows": get_leaderboard(db, selected_months=selected_months or None),
            "empty_state": {
                "title": "Пока нет ни одного визита",
                "hint": "Здесь появится статистика, как только амбассадоры начнут записывать визиты в мини-аппе.",
            },
        },
    )
