from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Sale
from ..render import render
from ..utils.dates import month_sort_key
from ..services.ambassadors_service import (
    build_ambassadors_report,
    normalize_selected_months,
)
from ..services.sales_options_service import (
    get_cities,
    get_months,
    get_clients,
)

router = APIRouter()


@router.get("/analytics/ambassadors")
def analytics_ambassadors(
    request: Request,
    db: Session = Depends(get_db),
):
    selected_city = (request.query_params.get("city") or "").strip()
    selected_months = request.query_params.getlist("months")
    selected_clients = request.query_params.getlist("clients")

    cities = get_cities(db)

    all_months = get_months(db, city=selected_city, reverse=True)

    all_clients = get_clients(db, city=selected_city)

    selected_months = normalize_selected_months(
        selected_months=selected_months,
        all_months=all_months,
    )

    selected_clients = [c for c in selected_clients if c in all_clients]

    report = build_ambassadors_report(
        db=db,
        selected_city=selected_city,
        selected_months=selected_months,
        selected_clients=selected_clients,
    )

    return render(
        request,
        "analytics/ambassadors.html",
        {
            "cities": cities,
            "all_months": all_months,
            "all_clients": all_clients,
            "selected_city": selected_city,
            "selected_months": selected_months,
            "selected_clients": selected_clients,
            "report": report,
        },
    )
