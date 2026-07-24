from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..auth_deps import require_user
from ..auth_models import User
from ..database import get_db
from ..models import AbcSegment, Sale
from ..render import render
from ..services.abc_service import (
    ensure_default_segments,
    get_client_abc_overview,
    guess_default_segment,
)
from ..services.ambassadors_service import (
    build_ambassadors_report,
    normalize_selected_months,
    sku_expr,
)
from ..services.client_analysis_service import (
    get_clients_rollup,
    get_nomenclature_rollup,
    get_types_rollup,
)
from ..services.sales_options_service import get_cities, get_clients, get_months
from ..utils.params import get_int_param

router = APIRouter()


@router.get("/analytics/client-analysis")
def client_analysis_page(
    request: Request,
    tab: str = "summary",
    city: str | None = None,
    months: list[str] = Query(default=None),
    clients: list[str] = Query(default=None),
    new_skus: list[str] = Query(default=None),
    db: Session = Depends(get_db),
    _user: User = Depends(require_user),
):
    active_tab = tab if tab in ("summary", "ambassadors") else "summary"

    cities = get_cities(db)

    ensure_default_segments(db)
    segments = db.query(AbcSegment).order_by(AbcSegment.sort_order, AbcSegment.id).all()
    segments_json = [{"id": s.id, "name": s.name} for s in segments]

    if not city:
        return render(
            request,
            "analytics/client_analysis.html",
            {
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
                "types": [],
                "first_type": None,
                "first_type_clients": [],
                "first_type_segment_id": None,
                "type_default_segment_id": {},
                "message": "Выберите нужный город",
            },
        )

    all_months = get_months(db, city=city, reverse=True)
    all_clients = get_clients(db, city=city)

    raw_selected_months = [m for m in (months or []) if m in all_months]
    selected_months = normalize_selected_months(
        selected_months=raw_selected_months,
        all_months=all_months,
    )
    selected_clients = [c for c in (clients or []) if c in all_clients]

    if active_tab == "ambassadors":
        status_settings = {
            "new_client_months": get_int_param(request, "new_client_months", 2),
            "lost_months": get_int_param(request, "lost_months", 2),
            "unstable_gap_months": get_int_param(request, "unstable_gap_months", 1),
        }
        selected_new_skus = new_skus or []

        sku_rows = (
            db.query(sku_expr().label("sku"))
            .filter(Sale.city == city)
            .distinct()
            .order_by(sku_expr())
            .all()
        )
        all_skus = [row.sku for row in sku_rows if row.sku]

        report = build_ambassadors_report(
            db=db,
            selected_city=city,
            selected_months=selected_months,
            selected_clients=selected_clients,
            selected_new_skus=selected_new_skus,
            status_settings=status_settings,
        )

        return render(
            request,
            "analytics/client_analysis.html",
            {
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
            },
        )

    types = get_types_rollup(
        db, city=city, months=selected_months, clients=selected_clients
    )

    type_default_segment_id = {
        t["type"]: (guess_default_segment(segments, t["type"]).id if segments else None)
        for t in types
    }

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
    _user: User = Depends(require_user),
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
    _user: User = Depends(require_user),
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
    _user: User = Depends(require_user),
):
    overview = get_client_abc_overview(
        db, city=city, client=client, sale_type=sale_type, segment_id=segment_id
    )
    missing = {
        category: [{"brand": p.brand, "flavor": p.flavor} for p in products]
        for category, products in overview["missing_by_category"].items()
    }
    return JSONResponse(missing)
