from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..auth_deps import require_admin, require_user
from ..auth_models import User
from ..database import get_db
from ..models import Sale
from ..render import render
from ..services.sale_filters import build_sale_filters
from ..services.charts_service import get_charts_metrics_data
from ..services.clients_service import (
    get_clients_summary_data,
    get_client_detail_data,
)
from ..services.sales_options_service import (
    get_cities,
    get_months,
    get_types,
    get_clients,
)

router = APIRouter()


@router.get("/analytics/clients")
def analytics_clients(
    request: Request,
    city: str | None = None,
    months: list[str] = Query(default=None),
    sale_types: list[str] = Query(default=None),
    matched: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_user),
):
    if _user.role != "admin":
        matched = None

    cities = get_cities(db)

    if not city:
        return render(
            request,
            "analytics/clients_summary.html",
            {
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
                "message": "Выберите нужный город",
            },
        )

    all_months = get_months(db, city=city, reverse=True)
    all_types = get_types(db, city=city)

    selected_months = months or []
    if all_months:
        selected_months = [m for m in selected_months if m in all_months]

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

    matched_flag = None
    if matched == "1":
        matched_flag = True
    elif matched == "0":
        matched_flag = False

    return render(
        request,
        "analytics/clients_summary.html",
        {
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
    _user: User = Depends(require_user),
):
    if _user.role != "admin":
        matched = None

    cities = get_cities(db)

    if not city:
        return render(
            request,
            "analytics/charts.html",
            {
                "cities": cities,
                "all_months": [],
                "all_types": [],
                "selected_city": None,
                "selected_months": [],
                "selected_types": [],
                "matched": None,
                "group": group,
                "all_clients": [],
                "selected_client": "",
                "message": "Выберите нужный город",
            },
        )

    all_months = get_months(db, city=city, reverse=True)
    all_types = get_types(db, city=city)

    selected_months = months or []
    if all_months:
        selected_months = [m for m in selected_months if m in all_months]

    selected_types = sale_types or []
    if all_types:
        selected_types = [t for t in selected_types if t in all_types]

    client_filters = build_sale_filters(
        city=city,
        months=selected_months,
        sale_types=selected_types,
        matched=matched,
    )

    all_clients = get_clients(db, filters=client_filters)

    matched_flag = None
    if matched == "1":
        matched_flag = True
    elif matched == "0":
        matched_flag = False

    return render(
        request,
        "analytics/charts.html",
        {
            "cities": cities,
            "all_months": all_months,
            "all_types": all_types,
            "selected_city": city,
            "selected_months": selected_months,
            "selected_types": selected_types,
            "matched": matched_flag,
            "group": group,
            "all_clients": all_clients,
            "selected_client": request.query_params.get("client") or "",
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
    _user: User = Depends(require_user),
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
    db: Session = Depends(get_db),
    _user: User = Depends(require_user),
):
    if _user.role != "admin":
        matched = None

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

    return render(
        request,
        "analytics/client_detail.html",
        {
            "rows": rows,
            "city": city,
            "client": client,
            "sale_type": sale_type,
            "months": months or [],
            "summary": summary,
        },
    )


@router.get("/admin/unmatched")
def unmatched_list(
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    rows = db.query(Sale).filter(Sale.matched.is_(False)).order_by(Sale.id.desc()).all()
    return render(request, "analytics/unmatched.html", {"rows": rows})
