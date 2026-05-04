from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Sale
from ..render import render
from ..services.ambassadors_service import (
    build_ambassadors_report,
    normalize_selected_months,
    sku_expr,
)
from ..services.sales_options_service import (
    get_cities,
    get_clients,
    get_months,
)

router = APIRouter()


def get_int_param(request: Request, name: str, default: int, min_value: int = 1) -> int:
    raw_value = request.query_params.get(name)

    if raw_value is None or raw_value == "":
        return default

    try:
        value = int(raw_value)
    except ValueError:
        return default

    return max(value, min_value)


@router.get("/analytics/ambassadors")
def analytics_ambassadors(
    request: Request,
    db: Session = Depends(get_db),
):
    selected_city = (request.query_params.get("city") or "").strip()
    selected_months = request.query_params.getlist("months")
    selected_clients = request.query_params.getlist("clients")
    selected_new_skus = request.query_params.getlist("new_skus")

    status_settings = {
        "new_client_months": get_int_param(request, "new_client_months", 2),
        "lost_months": get_int_param(request, "lost_months", 2),
        "unstable_gap_months": get_int_param(request, "unstable_gap_months", 1),
    }

    cities = get_cities(db)

    all_months = get_months(db, city=selected_city, reverse=True)

    all_clients = get_clients(db, city=selected_city)

    all_skus = []

    if selected_city:
        sku_rows = (
            db.query(sku_expr().label("sku"))
            .filter(Sale.city == selected_city)
            .distinct()
            .order_by(sku_expr())
            .all()
        )
        all_skus = [row.sku for row in sku_rows if row.sku]

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
        selected_new_skus=selected_new_skus,
        status_settings=status_settings,
    )

    return render(
        request,
        "analytics/ambassadors.html",
        {
            "cities": cities,
            "all_months": all_months,
            "all_clients": all_clients,
            "all_skus": all_skus,
            "selected_city": selected_city,
            "selected_months": selected_months,
            "selected_clients": selected_clients,
            "selected_new_skus": selected_new_skus,
            "status_settings": status_settings,
            "report": report,
        },
    )
