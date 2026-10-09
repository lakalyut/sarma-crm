from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..auth_deps import require_admin
from ..auth_models import User
from ..database import get_db
from ..render import render
from ..services.admin_workspace_service import recent_imports

router = APIRouter()


@router.get("/admin")
def admin_home(
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return render(
        request,
        "admin/home.html",
        {
            "title": "Администрирование — Пульс",
            "recent_imports": recent_imports(db, limit=5),
        },
    )
