from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ..auth_deps import require_user
from ..auth_models import User
from ..database import get_db
from ..render import render
from ..services import dashboard_service as svc
from ..services.sales_options_service import get_cities, get_months

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def dashboard_page(
    request: Request,
    cities: list[str] = Query(default=[]),
    months: list[str] = Query(default=[]),
    db: Session = Depends(get_db),
    _user: User = Depends(require_user),
):
    all_cities = get_cities(db)
    active_cities = cities or all_cities

    data = svc.get_regions_overview(db, active_cities, months)

    return render(
        request,
        "dashboard/dashboard.html",
        {
            "data": data,
            "metric_catalog": svc.METRIC_CATALOG,
            "all_cities": all_cities,
            "selected_cities": cities,
            "all_months": get_months(db),
            "selected_months": months,
        },
    )
