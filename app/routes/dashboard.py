from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ..auth_deps import require_user
from ..auth_models import User
from ..database import get_db
from ..render import render
from ..services import city_regions_service as regions_svc
from ..services import dashboard_service as svc
from ..services.sales_options_service import get_cities, get_months

router = APIRouter(prefix="/analytics/regions", tags=["regions"])


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
                "empty_state": {
                    "title": "Регионы не выбраны",
                    "hint": "Выберите один или несколько регионов в фильтре выше — здесь появится сводная таблица и график",
                },
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
    # Без выбранного макро-региона схлопывать нечего — city_to_region_name
    # пустой в обоих вызовах, detail_data вышел бы побайтово идентичен data
    # (сам get_regions_overview это подтверждает: CASE по пустому словарю
    # не меняет Sale.city). Второй проход по ~39к строк без индекса добавлял
    # почти секунду на пустом месте — держали в голове, что «Общий график»
    # и «По регионам отдельно» для отдельных городов и так совпадают
    # (см. CLAUDE.md, раздел «Дашборд»), просто не переиспользовали расчёт.
    detail_data = (
        data
        if not city_to_region_name
        else svc.get_regions_overview(db, query_cities, months)
    )

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
