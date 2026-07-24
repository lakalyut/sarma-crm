from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..auth_deps import require_user
from ..auth_models import User
from ..database import get_db
from ..models import AbcSegment
from ..render import render
from ..services.abc_service import ensure_default_segments, get_client_abc_overview
from ..services.ambassadors_service import normalize_selected_months
from ..services.client_analysis_service import (
    get_clients_rollup,
    get_nomenclature_rollup,
    get_types_rollup,
)
from ..services.sales_options_service import get_cities, get_clients, get_months

router = APIRouter()


@router.get("/analytics/client-analysis")
def client_analysis_page(
    request: Request,
    city: str | None = None,
    months: list[str] = Query(default=None),
    clients: list[str] = Query(default=None),
    segment_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_user),
):
    cities = get_cities(db)

    ensure_default_segments(db)
    segments = db.query(AbcSegment).order_by(AbcSegment.sort_order, AbcSegment.id).all()

    selected_segment = None
    if segment_id:
        selected_segment = next((s for s in segments if s.id == segment_id), None)
    if not selected_segment and segments:
        selected_segment = segments[0]

    if not city:
        return render(
            request,
            "analytics/client_analysis.html",
            {
                "cities": cities,
                "all_months": [],
                "all_clients": [],
                "selected_city": None,
                "selected_months": [],
                "raw_selected_months": [],
                "selected_clients": clients or [],
                "segments": segments,
                "selected_segment": selected_segment,
                "types": [],
                "first_type": None,
                "first_type_clients": [],
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

    types = get_types_rollup(
        db, city=city, months=selected_months, clients=selected_clients
    )

    first_type = types[0]["type"] if types else None
    first_type_clients = []
    if first_type:
        first_type_clients = get_clients_rollup(
            db,
            city=city,
            sale_type=first_type,
            months=selected_months,
            clients=selected_clients,
            segment_id=selected_segment.id if selected_segment else None,
        )

    return render(
        request,
        "analytics/client_analysis.html",
        {
            "cities": cities,
            "all_months": all_months,
            "all_clients": all_clients,
            "selected_city": city,
            "selected_months": selected_months,
            "raw_selected_months": raw_selected_months,
            "selected_clients": selected_clients,
            "segments": segments,
            "selected_segment": selected_segment,
            "types": types,
            "first_type": first_type,
            "first_type_clients": first_type_clients,
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
