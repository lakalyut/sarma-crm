from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..auth_deps import require_analyst
from ..auth_models import User
from ..database import get_db
from ..models import AbcSegment, ProductAbcRating
from ..render import render
from ..services.abc_service import (
    ensure_default_segments,
    get_client_abc_overview,
    guess_default_segment,
)
from ..services.ambassador_service import get_visit_clients, get_visit_months
from ..services.ambassadors_service import (
    build_ambassadors_report,
    get_distinct_skus,
    normalize_selected_months,
)
from ..services.client_analysis_service import (
    get_clients_rollup,
    get_nomenclature_rollup,
    get_summary_totals,
    get_types_rollup,
)
from ..services.client_health_service import build_client_health
from ..services.sales_options_service import get_cities, get_clients, get_months
from ..services.sku_presence_service import build_sku_presence, get_sku_options
from ..services.visit_analysis_service import get_visit_analysis
from ..services.visit_effectiveness_service import build_visit_effectiveness_report
from ..utils.dates import month_sort_key, parse_month
from ..utils.params import get_int_param

# Вкладки, которые про визиты, а не про продажи: их пикер периода и список
# клиентов дополняются данными из Visit (месяц/клиент визита, за который
# импорта Sale ещё нет, иначе не виден).
_VISIT_TABS = ("visit_analysis", "visit_effectiveness")

router = APIRouter()


@router.get("/analytics/client-analysis")
def client_analysis_page(
    request: Request,
    tab: str = "summary",
    city: str | None = None,
    months: list[str] = Query(default=None),
    clients: list[str] = Query(default=None),
    new_skus: list[str] = Query(default=None),
    skus: list[str] = Query(default=None),
    abc_segment: list[int] = Query(default=[]),
    db: Session = Depends(get_db),
    _user: User = Depends(require_analyst),
):
    active_tab = (
        tab
        if tab
        in (
            "summary",
            "ambassadors",
            "visit_effectiveness",
            "visit_analysis",
            "sku_presence",
            "client_health",
        )
        else "summary"
    )

    cities = get_cities(db)

    ensure_default_segments(db)
    segments = db.query(AbcSegment).order_by(AbcSegment.sort_order, AbcSegment.id).all()
    segments_json = [{"id": s.id, "name": s.name} for s in segments]

    if not city:
        return render(
            request,
            "analytics/client_analysis.html",
            {
                "title": "Аналитика по клиентам — Пульс",
                "active_tab": active_tab,
                "cities": cities,
                "all_months": [],
                "all_clients": [],
                "all_skus": [],
                "selected_city": None,
                "selected_months": [],
                "raw_selected_months": [],
                "selected_clients": clients or [],
                "selected_new_skus": new_skus or [],
                "status_settings": {
                    "new_client_months": 2,
                    "lost_months": 2,
                    "unstable_gap_months": 1,
                },
                "report": {"months": [], "clients": []},
                "segments_json": segments_json,
                "rating_by_client": {},
                "segment_id_by_client": {},
                "types": [],
                "first_type": None,
                "first_type_clients": [],
                "first_type_segment_id": None,
                "type_default_segment_id": {},
                "summary_totals": {
                    "labels": [],
                    "weight": [],
                    "qty": [],
                    "unique_sku": [],
                },
                "sku_options": [],
                "selected_skus": [],
                "selected_segment_id": None,
                "sku_presence": {"rows": [], "sku_count": 0},
                "health": {"months": [], "rows": [], "status_counts": {}},
                "empty_state": {
                    "hint": "Выберите регион в фильтре выше — здесь появится анализ по клиентам"
                },
            },
        )

    all_months = get_months(db, city=city, reverse=True)
    if active_tab in _VISIT_TABS:
        # Продажи приходят с опозданием на месяц (сентябрьские грузят в
        # октябре), а визиты идут в текущем месяце — иначе месяц визита не
        # выбрать в пикере. Дедуп по (год, месяц) через parse_month: когда
        # продажи за этот месяц наконец подъедут (в своём формате —
        # «Сентябрь 2026» или ISO), ISO-месяц из визита в список НЕ
        # добавляется, чтобы не было двух «Сентябрь 2026».
        known = {parse_month(m) for m in all_months}
        known.discard(None)
        extra = [m for m in get_visit_months(db, city) if parse_month(m) not in known]
        all_months = sorted(
            set(all_months) | set(extra), key=month_sort_key, reverse=True
        )

    raw_selected_months = [m for m in (months or []) if m in all_months]
    selected_months = normalize_selected_months(
        selected_months=raw_selected_months,
        all_months=all_months,
    )

    all_clients = get_clients(db, city=city, months=raw_selected_months)
    if active_tab in _VISIT_TABS:
        all_clients = sorted(set(all_clients) | set(get_visit_clients(db, city)))
    selected_clients = [c for c in (clients or []) if c in all_clients]

    if active_tab == "ambassadors":
        status_settings = {
            "new_client_months": get_int_param(request, "new_client_months", 2),
            "lost_months": get_int_param(request, "lost_months", 2),
            "unstable_gap_months": get_int_param(request, "unstable_gap_months", 1),
        }
        selected_new_skus = new_skus or []

        all_skus = get_distinct_skus(db, city)

        report = build_ambassadors_report(
            db=db,
            selected_city=city,
            selected_months=selected_months,
            selected_clients=selected_clients,
            selected_new_skus=selected_new_skus,
            status_settings=status_settings,
        )

        # Сегмент ABC — свой на каждого клиента (не общий на всю вкладку, по
        # аналогии со "Сводом", где сегмент свой на каждый тип точки). Один
        # <select> на карточку клиента, submit кладёт значения в abc_segment
        # в том же порядке, что и клиенты — report.clients уже гарантированно
        # в порядке selected_clients (build_ambassadors_report так строит).
        valid_segment_ids = {s.id for s in segments}
        default_segment_id = segments[0].id if segments else None
        segment_id_by_client: dict[str, int | None] = {}
        for i, client_name in enumerate(selected_clients):
            candidate = abc_segment[i] if i < len(abc_segment) else None
            segment_id_by_client[client_name] = (
                candidate if candidate in valid_segment_ids else default_segment_id
            )

        unique_segment_ids = {v for v in segment_id_by_client.values() if v}
        ratings_by_segment: dict[int, dict[int, str]] = {}
        if unique_segment_ids:
            ratings = (
                db.query(ProductAbcRating)
                .filter(ProductAbcRating.segment_id.in_(unique_segment_ids))
                .all()
            )
            for r in ratings:
                ratings_by_segment.setdefault(r.segment_id, {})[
                    r.product_id
                ] = r.category

        rating_by_client = {
            client_name: ratings_by_segment.get(segment_id, {})
            for client_name, segment_id in segment_id_by_client.items()
        }

        return render(
            request,
            "analytics/client_analysis.html",
            {
                "title": "Аналитика по клиентам — Пульс",
                "active_tab": active_tab,
                "cities": cities,
                "all_months": all_months,
                "all_clients": all_clients,
                "all_skus": all_skus,
                "selected_city": city,
                "selected_months": selected_months,
                "raw_selected_months": raw_selected_months,
                "selected_clients": selected_clients,
                "selected_new_skus": selected_new_skus,
                "status_settings": status_settings,
                "report": report,
                "segments_json": segments_json,
                "rating_by_client": rating_by_client,
                "segment_id_by_client": segment_id_by_client,
            },
        )

    if active_tab == "visit_effectiveness":
        report = build_visit_effectiveness_report(
            db,
            city=city,
            selected_months=selected_months,
            selected_clients=selected_clients,
        )

        return render(
            request,
            "analytics/client_analysis.html",
            {
                "title": "Аналитика по клиентам — Пульс",
                "active_tab": active_tab,
                "cities": cities,
                "all_months": all_months,
                "all_clients": all_clients,
                "selected_city": city,
                "selected_months": selected_months,
                "raw_selected_months": raw_selected_months,
                "selected_clients": selected_clients,
                "report": report,
            },
        )

    if active_tab == "visit_analysis":
        # Фильтр по месяцам — только по явно выбранным (raw_selected_months),
        # не по normalize-to-all: визиты пишутся «сейчас», часто в месяц, за
        # который ещё нет импорта продаж, а normalize подставил бы все
        # месяцы из Sale и скрыл бы свежие визиты.
        visit_rows = get_visit_analysis(
            db,
            city=city,
            selected_months=raw_selected_months,
            selected_clients=selected_clients,
        )

        return render(
            request,
            "analytics/client_analysis.html",
            {
                "title": "Аналитика по клиентам — Пульс",
                "active_tab": active_tab,
                "cities": cities,
                "all_months": all_months,
                "all_clients": all_clients,
                "selected_city": city,
                "selected_months": raw_selected_months,
                "raw_selected_months": raw_selected_months,
                "selected_clients": selected_clients,
                "visit_rows": visit_rows,
            },
        )

    if active_tab == "sku_presence":
        valid_segment_ids = {s.id for s in segments}
        selected_segment_id = next(
            (sid for sid in abc_segment if sid in valid_segment_ids), None
        ) or (segments[0].id if segments else None)

        sku_options = get_sku_options(db, city, selected_segment_id)
        valid_skus = {o["sku"] for o in sku_options}
        selected_skus = [s for s in (skus or []) if s in valid_skus]

        presence = build_sku_presence(
            db, city=city, selected_months=selected_months, selected_skus=selected_skus
        )

        return render(
            request,
            "analytics/client_analysis.html",
            {
                "title": "Аналитика по клиентам — Пульс",
                "active_tab": active_tab,
                "cities": cities,
                "all_months": all_months,
                "all_clients": all_clients,
                "selected_city": city,
                "selected_months": selected_months,
                "raw_selected_months": raw_selected_months,
                "selected_clients": selected_clients,
                "segments_json": segments_json,
                "sku_options": sku_options,
                "selected_skus": selected_skus,
                "selected_segment_id": selected_segment_id,
                "sku_presence": presence,
            },
        )

    if active_tab == "client_health":
        status_settings = {
            "new_client_months": get_int_param(request, "new_client_months", 2),
            "lost_months": get_int_param(request, "lost_months", 2),
            "unstable_gap_months": get_int_param(request, "unstable_gap_months", 1),
        }

        health = build_client_health(
            db=db,
            city=city,
            selected_months=selected_months,
            status_settings=status_settings,
        )

        return render(
            request,
            "analytics/client_analysis.html",
            {
                "title": "Аналитика по клиентам — Пульс",
                "active_tab": active_tab,
                "cities": cities,
                "all_months": all_months,
                "all_clients": all_clients,
                "selected_city": city,
                "selected_months": selected_months,
                "raw_selected_months": raw_selected_months,
                "selected_clients": selected_clients,
                "status_settings": status_settings,
                "health": health,
            },
        )

    types = get_types_rollup(
        db, city=city, months=selected_months, clients=selected_clients
    )

    type_default_segment_id = {
        t["type"]: (guess_default_segment(segments, t["type"]).id if segments else None)
        for t in types
    }

    summary_totals = get_summary_totals(
        db, city=city, months=selected_months, clients=selected_clients
    )

    first_type = types[0]["type"] if types else None
    first_type_segment_id = (
        type_default_segment_id.get(first_type) if first_type else None
    )
    first_type_clients = []
    if first_type:
        first_type_clients = get_clients_rollup(
            db,
            city=city,
            sale_type=first_type,
            months=selected_months,
            clients=selected_clients,
            segment_id=first_type_segment_id,
        )

    return render(
        request,
        "analytics/client_analysis.html",
        {
            "title": "Аналитика по клиентам — Пульс",
            "active_tab": active_tab,
            "cities": cities,
            "all_months": all_months,
            "all_clients": all_clients,
            "selected_city": city,
            "selected_months": selected_months,
            "raw_selected_months": raw_selected_months,
            "selected_clients": selected_clients,
            "segments_json": segments_json,
            "types": types,
            "first_type": first_type,
            "first_type_clients": first_type_clients,
            "first_type_segment_id": first_type_segment_id,
            "type_default_segment_id": type_default_segment_id,
            "summary_totals": summary_totals,
        },
    )


@router.get("/api/client-analysis/clients")
def api_client_analysis_clients(
    city: str,
    sale_type: str,
    months: list[str] = Query(default=None),
    clients: list[str] = Query(default=None),
    segment_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_analyst),
):
    rows = get_clients_rollup(
        db,
        city=city,
        sale_type=sale_type,
        months=months,
        clients=clients,
        segment_id=segment_id,
    )
    return JSONResponse(rows)


@router.get("/api/client-analysis/nomenclature")
def api_client_analysis_nomenclature(
    city: str,
    client: str,
    sale_type: str,
    months: list[str] = Query(default=None),
    db: Session = Depends(get_db),
    _user: User = Depends(require_analyst),
):
    rows = get_nomenclature_rollup(
        db, city=city, client=client, sale_type=sale_type, months=months
    )
    return JSONResponse(rows)


@router.get("/api/client-analysis/missing")
def api_client_analysis_missing(
    city: str,
    client: str,
    sale_type: str,
    segment_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_analyst),
):
    overview = get_client_abc_overview(
        db, city=city, client=client, sale_type=sale_type, segment_id=segment_id
    )
    missing = {
        category: [{"brand": p.brand, "flavor": p.flavor} for p in products]
        for category, products in overview["missing_by_category"].items()
    }
    return JSONResponse(missing)
