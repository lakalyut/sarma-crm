from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..auth_deps import require_analyst
from ..auth_models import User
from ..database import get_db
from ..render import render
from ..services.leaderboard_service import get_leaderboard

router = APIRouter()


@router.get("/leaderboard")
def leaderboard_page(
    request: Request,
    db: Session = Depends(get_db),
    _user: User = Depends(require_analyst),
):
    return render(
        request,
        "leaderboard/leaderboard.html",
        {
            "title": "Лидерборд — Пульс",
            "rows": get_leaderboard(db),
            "empty_state": {
                "title": "Пока нет ни одного визита",
                "hint": "Здесь появится статистика, как только амбассадоры начнут записывать визиты в мини-аппе.",
            },
        },
    )
