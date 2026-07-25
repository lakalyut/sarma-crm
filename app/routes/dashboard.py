from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ..auth_deps import require_user
from ..auth_models import User
from ..database import get_db
from ..render import render
from ..services import city_regions_service as regions_svc
from ..services import dashboard_service as svc
from ..services.sales_options_service import get_cities, get_months

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def dashboard_page(
    request: Request,
    cities: list[str] = Query(default=[]),
    regions: list[str] = Query(default=[]),
    months: list[str] = Query(default=[]),
    db: Session = Depends(get_db),
    _user: User = Depends(require_user),
):
    all_cities = get_cities(db)
    all_regions = regions_svc.get_regions(db)

    if not cities and not regions:
        return render(
            request,
            "dashboard/dashboard.html",
            {
                "title": "Аналитика по регионам — Пульс",
                "data": {"cities": [], "months": [], "month_labels": [], "metrics": {}},
                "detail_data": {
                    "cities": [],
                    "months": [],
                    "month_labels": [],
                    "metrics": {},
                },
                "metric_catalog": svc.METRIC_CATALOG,
                "all_cities": all_cities,
                "all_regions": all_regions,
                "selected_cities": [],
                "selected_regions": [],
                "all_months": get_months(db),
                "selected_months": months,
                "message": "Выберите один или несколько регионов для сравнения",
            },
        )

    valid_region_names = {r.name for r in all_regions}
    selected_regions = [r for r in regions if r in valid_region_names]

    city_region_map = regions_svc.get_city_region_map(db)
    city_to_region_name = {
        city: cr.region.name
        for city, cr in city_region_map.items()
        if cr.region.name in selected_regions
    }

    query_cities = [c for c in cities if c in all_cities] + list(
        city_to_region_name.keys()
    )

    data = svc.get_regions_overview(db, query_cities, months, city_to_region_name)
    detail_data = svc.get_regions_overview(db, query_cities, months)

    return render(
        request,
        "dashboard/dashboard.html",
        {
            "title": "Аналитика по регионам — Пульс",
            "data": data,
            "detail_data": detail_data,
            "metric_catalog": svc.METRIC_CATALOG,
            "all_cities": all_cities,
            "all_regions": all_regions,
            "selected_cities": cities,
            "selected_regions": selected_regions,
            "all_months": get_months(db),
            "selected_months": months,
        },
    )
