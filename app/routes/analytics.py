from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.status import HTTP_302_FOUND

from ..auth_deps import require_analyst, require_client_viewer
from ..auth_models import User
from ..database import get_db
from ..models import AbcSegment
from ..render import render
from ..services.abc_service import (
    ensure_default_segments,
    get_client_abc_overview,
    guess_default_segment,
)
from ..services.ambassadors_service import (
    build_client_sku_status,
    normalize_selected_months,
)
from ..services.analytics_settings_service import (
    get_analytics_settings,
    get_sku_status_settings,
    status_history_length,
)
from ..services.charts_service import get_charts_metrics_data
from ..services.client_health_service import STATUS_ORDER, build_client_health
from ..services.client_segments_service import (
    build_client_segments,
    month_value,
    shift_month,
)
from ..services.clients_service import (
    get_client_detail_data,
    get_clients_summary_data,
)
from ..services.sale_filters import build_sale_filters
from ..services.sales_options_service import get_cities, get_months, get_types
from ..templating import templates
from ..utils.dates import month_sort_key, parse_month
from ..utils.params import get_int_param

router = APIRouter()


def _segment_months(db: Session, city: str, today: date) -> list[tuple[int, int]]:
    if not city:
        return []
    return sorted(
        {
            month
            for raw in get_months(db, city=city)
            if (month := parse_month(raw))
            and (1, 1) <= month <= (today.year, today.month)
        },
        reverse=True,
    )


@router.get("/api/clients/abc-xyz/options")
def client_segment_options(
    city: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_client_viewer),
):
    if user.role == "ambassador":
        city = user.city or ""
    today = datetime.now(ZoneInfo("Asia/Irkutsk")).date()
    return {
        "types": get_types(db, city=city) if city else [],
        "month_picker": templates.get_template(
            "analytics/_client_segments_months.html"
        ).render(
            all_months=[
                month_value(month) + "-01" for month in _segment_months(db, city, today)
            ],
            selected_months=[],
            selected_city=city,
        ),
    }


@router.get("/analytics/clients/abc-xyz")
def client_segments(
    request: Request,
    city: str = "",
    months: list[str] | None = Query(default=None),
    length: int | None = None,
    end: str = "",
    sale_type: str = "",
    mode: Literal["volume", "presence"] = "volume",
    db: Session = Depends(get_db),
    user: User = Depends(require_client_viewer),
):
    today = datetime.now(ZoneInfo("Asia/Irkutsk")).date()
    cities = get_cities(db)
    if user.role == "ambassador":
        city = user.city or ""
        cities = [city] if city else []
    elif user.role == "brand_ambassador":
        cities = [value for value in cities if value in user.allowed_cities]
    sale_types = get_types(db, city=city) if city else []
    if sale_type and sale_type not in sale_types:
        raise HTTPException(400, "Выберите тип точки из списка выбранного города")
    available = _segment_months(db, city, today)
    selected = []
    if months:
        requested = {parse_month(month) for month in months}
        selected = [month for month in available if month in requested]
    elif available or end or length is not None:
        # Старые ссылки задают календарное окно, из которого берём загруженные месяцы.
        if length not in (None, 6, 12):
            raise HTTPException(400, "Выберите период 6 или 12 месяцев")
        if end:
            try:
                parsed = date.fromisoformat(end + "-01")
            except ValueError as exc:
                raise HTTPException(400, "Некорректный месяц окончания") from exc
            if parsed >= today.replace(day=1):
                raise HTTPException(400, "Выберите завершённый месяц")
            end_month = (parsed.year, parsed.month)
        else:
            last_closed = shift_month((today.year, today.month), -1)
            end_month = next(
                (month for month in available if month <= last_closed), last_closed
            )
        start_month = shift_month(
            end_month,
            1 - (length or get_analytics_settings(db)["client_segments_months"]),
        )
        selected = [month for month in available if start_month <= month <= end_month]
    report = (
        build_client_segments(
            db,
            city,
            months=selected,
            sale_type=sale_type,
            mode=mode,
        )
        if selected
        else None
    )
    return render(
        request,
        "analytics/client_segments.html",
        {
            "title": "ABC / XYZ клиентов — Пульс",
            "selected_city": city,
            "cities": cities,
            "sale_types": sale_types,
            "selected_type": sale_type,
            "all_months": [month_value(month) + "-01" for month in available],
            "selected_months": [month_value(month) + "-01" for month in selected],
            "period_months": [month_value(month) + "-01" for month in selected],
            "mode": mode,
            "report": report,
            **_layout_context(user),
        },
    )


def _layout_context(user: User) -> dict:
    """Амбассадор видит «Клиенты»/детализацию в своём минимальном layout без
    сайдбара; аналитики — как обычно. `ambassador_mode` глушит в шаблонах
    аналитик-специфичные блоки (поиск региона, панель «Сформировать свод»).
    `wide_content` расширяет узкий (640px) контейнер base_ambassador.html под
    широкие таблицы этих страниц — на обычном base.html флаг игнорируется."""
    ambassador_mode = user.role == "ambassador"
    return {
        "ambassador_mode": ambassador_mode,
        "base_template": "base_ambassador.html" if ambassador_mode else "base.html",
        "wide_content": ambassador_mode,
    }


@router.get("/analytics/clients")
def analytics_clients(
    request: Request,
    city: str | None = None,
    months: list[str] = Query(default=None),
    sale_types: list[str] = Query(default=None),
    matched: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_client_viewer),
):
    if _user.role != "admin":
        matched = None

    if _user.role == "ambassador":
        if not _user.city:
            return RedirectResponse("/ambassador/profile", status_code=HTTP_302_FOUND)
        city = _user.city

    layout = _layout_context(_user)
    cities = get_cities(db)

    if not city:
        return render(
            request,
            "analytics/clients_summary.html",
            {
                "title": "Клиенты — Пульс",
                "rows": [],
                "cities": cities,
                "all_months": [],
                "all_types": [],
                "selected_city": None,
                "selected_months": [],
                "selected_types": [],
                "matched": None,
                "summary": {
                    "unique_clients": 0,
                    "total_qty": 0,
                    "total_weight": 0,
                    "unique_sku": 0,
                    "total_sku": 0,
                    "sku_per_client": 0,
                },
                "type_cards": [],
                "monthly_by_client": {},
                "client_health_by_key": {},
                "empty_state": {
                    "hint": "Выберите регион в фильтре выше — здесь появится сводка по клиентам"
                },
                **layout,
            },
        )

    all_months = get_months(db, city=city, reverse=True)

    selected_months = months or []
    if all_months:
        selected_months = [m for m in selected_months if m in all_months]

    all_types = get_types(db, city=city, months=selected_months)

    selected_types = sale_types or []
    if all_types:
        selected_types = [t for t in selected_types if t in all_types]

    filters = build_sale_filters(
        city=city,
        months=selected_months,
        sale_types=selected_types,
        matched=matched,
    )

    clients_data = get_clients_summary_data(
        db=db,
        filters=filters,
    )

    rows = clients_data["rows"]
    summary = clients_data["summary"]
    type_cards = clients_data["type_cards"]
    monthly_by_client = clients_data["monthly_by_client"]

    # Явный выбор месяцев имеет приоритет над общим окном статусов.
    client_health_by_key = {}
    if all_months:
        settings = get_analytics_settings(db)
        health_months = selected_months or all_months[: status_history_length(settings)]
        health = build_client_health(
            db=db,
            city=city,
            selected_months=sorted(health_months, key=month_sort_key),
            status_settings=settings,
        )
        client_health_by_key = {
            (r["client"], r["sale_type"]): {
                **r,
                "status_rank": STATUS_ORDER.index(r["status"]),
            }
            for r in health["rows"]
        }

    matched_flag = None
    if matched == "1":
        matched_flag = True
    elif matched == "0":
        matched_flag = False

    return render(
        request,
        "analytics/clients_summary.html",
        {
            "title": "Клиенты — Пульс",
            "rows": rows,
            "cities": cities,
            "all_months": all_months,
            "all_types": all_types,
            "selected_city": city,
            "selected_months": selected_months,
            "selected_types": selected_types,
            "matched": matched_flag,
            "summary": summary,
            "type_cards": type_cards,
            "monthly_by_client": monthly_by_client,
            "client_health_by_key": client_health_by_key,
            **layout,
        },
    )


@router.get("/analytics/charts")
def analytics_charts(
    request: Request,
    city: str | None = None,
    months: list[str] = Query(default=None),
    sale_types: list[str] = Query(default=None),
    matched: str | None = None,
    group: str = "total",
    db: Session = Depends(get_db),
    _user: User = Depends(require_analyst),
):
    if _user.role != "admin":
        matched = None

    cities = get_cities(db)

    if not city:
        return render(
            request,
            "analytics/charts.html",
            {
                "title": "Графики — Пульс",
                "cities": cities,
                "all_months": [],
                "all_types": [],
                "selected_city": None,
                "selected_months": [],
                "selected_types": [],
                "matched": None,
                "group": group,
                "empty_state": {
                    "hint": "Выберите регион в фильтре выше — здесь появится динамика"
                },
            },
        )

    all_months = get_months(db, city=city, reverse=True)

    selected_months = months or []
    if all_months:
        selected_months = [m for m in selected_months if m in all_months]

    all_types = get_types(db, city=city, months=selected_months)

    selected_types = sale_types or []
    if all_types:
        selected_types = [t for t in selected_types if t in all_types]

    matched_flag = None
    if matched == "1":
        matched_flag = True
    elif matched == "0":
        matched_flag = False

    return render(
        request,
        "analytics/charts.html",
        {
            "title": "Графики — Пульс",
            "cities": cities,
            "all_months": all_months,
            "all_types": all_types,
            "selected_city": city,
            "selected_months": selected_months,
            "selected_types": selected_types,
            "matched": matched_flag,
            "group": group,
        },
    )


@router.get("/api/charts/metrics")
def api_charts_metrics(
    city: str | None = None,
    months: list[str] = Query(default=None),
    sale_types: list[str] = Query(default=None),
    matched: str | None = None,
    group: str = "total",
    client: str | None = None,
    sale_type: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_analyst),
):
    if _user.role != "admin":
        matched = None

    if not city:
        return JSONResponse(
            {"labels": [], "series": [], "message": "Выберите нужный город"}
        )

    filters = build_sale_filters(
        city=city,
        months=months,
        sale_types=sale_types,
        client=client,
        sale_type=sale_type,
        matched=matched,
    )

    data = get_charts_metrics_data(
        db=db,
        filters=filters,
        group=group,
    )

    return JSONResponse(data)


@router.get("/analytics/client")
def analytics_client_detail(
    request: Request,
    city: str,
    client: str,
    sale_type: str,
    months: list[str] = Query(default=None),
    matched: str | None = None,
    abc_segment: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_client_viewer),
):
    if _user.role != "admin":
        matched = None

    if _user.role == "ambassador":
        if not _user.city:
            return RedirectResponse("/ambassador/profile", status_code=HTTP_302_FOUND)
        city = _user.city

    layout = _layout_context(_user)

    detail_data = get_client_detail_data(
        db=db,
        city=city,
        client=client,
        sale_type=sale_type,
        months=months,
        matched=matched,
    )

    rows = detail_data["rows"]
    summary = detail_data["summary"]
    monthly = detail_data["monthly"]

    ensure_default_segments(db)
    segments = db.query(AbcSegment).order_by(AbcSegment.sort_order, AbcSegment.id).all()

    selected_segment = None
    if abc_segment:
        selected_segment = next((s for s in segments if s.id == abc_segment), None)
    if not selected_segment:
        selected_segment = guess_default_segment(segments, sale_type)

    abc_overview = None
    rating_by_product: dict[int, str] = {}
    if selected_segment:
        abc_overview = get_client_abc_overview(
            db=db,
            city=city,
            client=client,
            sale_type=sale_type,
            segment_id=selected_segment.id,
        )
        rating_by_product = abc_overview["rating_by_product"]

    defaults = get_sku_status_settings(db)
    status_settings = {
        "new_client_months": get_int_param(
            request, "new_client_months", defaults["new_client_months"]
        ),
        "lost_months": get_int_param(request, "lost_months", defaults["lost_months"]),
        "unstable_gap_months": get_int_param(
            request, "unstable_gap_months", defaults["unstable_gap_months"]
        ),
    }

    all_months = get_months(db, city=city, reverse=True)
    status_months = normalize_selected_months(
        selected_months=months or [],
        all_months=all_months,
    )
    sku_status = build_client_sku_status(
        db=db,
        city=city,
        client=client,
        sale_type=sale_type,
        selected_months=status_months,
        status_settings=status_settings,
    )

    return render(
        request,
        "analytics/client_detail.html",
        {
            "title": f"{client} — Пульс",
            "rows": rows,
            "city": city,
            "client": client,
            "sale_type": sale_type,
            "months": months or [],
            "summary": summary,
            "monthly": monthly,
            "segments": segments,
            "selected_segment": selected_segment,
            "abc_overview": abc_overview,
            "rating_by_product": rating_by_product,
            "matched": matched,
            "status_settings": status_settings,
            "sku_status": sku_status,
            **layout,
        },
    )


# /admin/unmatched переехал в routes/admin_unmatched.py — там же правка/
# удаление/ручное сопоставление строк.
