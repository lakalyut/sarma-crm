from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ..auth_deps import require_analyst
from ..auth_models import User
from ..database import get_db
from ..render import render
from ..services.leaderboard_service import get_leaderboard_page_data

router = APIRouter()


@router.get("/leaderboard")
def leaderboard_page(
    request: Request,
    months: list[str] = Query(default=None),
    db: Session = Depends(get_db),
    _user: User = Depends(require_analyst),
):
    return render(
        request,
        "leaderboard/leaderboard.html",
        {
            "title": "Лидерборд — Пульс",
            **get_leaderboard_page_data(db, months),
            "empty_state": {
                "title": "Пока нет ни одного визита",
                "hint": "Здесь появится статистика, как только амбассадоры начнут записывать визиты в мини-аппе.",
            },
        },
    )
