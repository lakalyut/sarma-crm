from collections import defaultdict

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth_deps import require_admin, require_user
from ..auth_models import User
from ..database import get_db
from ..models import Sale
from ..render import render
from ..templating import templates
from ..utils.dates import month_sort_key

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

    cities = [c[0] for c in db.query(Sale.city).distinct().order_by(Sale.city) if c[0]]

    months_query = db.query(Sale.month).distinct()

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

    if city:
        months_query = months_query.filter(Sale.city == city)
    all_months = [m[0] for m in months_query if m[0]]
    all_months = sorted(all_months, key=month_sort_key, reverse=True)

    types_query = db.query(Sale.type).distinct()
    if city:
        types_query = types_query.filter(Sale.city == city)
    all_types = [t[0] for t in types_query.order_by(Sale.type) if t[0]]

    selected_months = months or []
    if all_months:
        selected_months = [m for m in selected_months if m in all_months]

    selected_types = sale_types or []
    if all_types:
        selected_types = [t for t in selected_types if t in all_types]

    filters = []
    if city:
        filters.append(Sale.city == city)
    if selected_months:
        filters.append(Sale.month.in_(selected_months))
    if selected_types:
        filters.append(Sale.type.in_(selected_types))

    if matched == "1":
        filters.append(Sale.matched.is_(True))
    elif matched == "0":
        filters.append(Sale.matched.is_(False))

    q = db.query(
        Sale.type.label("type"),
        Sale.client.label("client"),
        func.sum(Sale.qty).label("qty"),
        func.sum(Sale.weight).label("weight"),
        func.count(func.distinct(Sale.sku)).label("sku_count"),
    )
    if filters:
        q = q.filter(*filters)

    q = q.group_by(Sale.type, Sale.client).order_by(Sale.type, Sale.client)
    rows = q.all()

    client_q = db.query(func.count(func.distinct(Sale.client)))
    if filters:
        client_q = client_q.filter(*filters)
    unique_clients = int(client_q.scalar() or 0)

    sku_q = db.query(func.count(func.distinct(Sale.sku)))
    if filters:
        sku_q = sku_q.filter(*filters)
    unique_sku = int(sku_q.scalar() or 0)

    sums_q = db.query(
        func.sum(Sale.qty).label("qty_sum"),
        func.sum(Sale.weight).label("weight_sum"),
    )
    if filters:
        sums_q = sums_q.filter(*filters)
    sums = sums_q.one()

    total_qty = float(sums.qty_sum or 0)
    total_weight = float(sums.weight_sum or 0)
    total_sku = int(sum(r.sku_count or 0 for r in rows)) if rows else 0

    type_cards = []
    if rows:
        type_counts = defaultdict(int)
        for r in rows:
            t = r.type or "—"
            type_counts[t] += 1
        type_cards = [{"type": t, "clients": cnt} for t, cnt in type_counts.items()]
        type_cards.sort(key=lambda x: str(x["type"]))

    summary = {
        "unique_clients": unique_clients,
        "total_qty": total_qty,
        "total_weight": total_weight,
        "unique_sku": unique_sku,
        "total_sku": total_sku,
        "sku_per_client": (
            (float(total_sku) / unique_clients) if unique_clients else 0.0
        ),
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
    cities = [c[0] for c in db.query(Sale.city).distinct().order_by(Sale.city) if c[0]]

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

    months_q = db.query(Sale.month).distinct()
    if city:
        months_q = months_q.filter(Sale.city == city)
    all_months = [m[0] for m in months_q if m[0]]
    all_months = sorted(all_months, key=month_sort_key, reverse=True)

    types_q = db.query(Sale.type).distinct()
    if city:
        types_q = types_q.filter(Sale.city == city)
    all_types = [t[0] for t in types_q.order_by(Sale.type) if t[0]]

    selected_months = months or []
    if all_months:
        selected_months = [m for m in selected_months if m in all_months]

    selected_types = sale_types or []
    if all_types:
        selected_types = [t for t in selected_types if t in all_types]

    client_filters = []
    if city:
        client_filters.append(Sale.city == city)
    if selected_months:
        client_filters.append(Sale.month.in_(selected_months))
    if selected_types:
        client_filters.append(Sale.type.in_(selected_types))
    if matched == "1":
        client_filters.append(Sale.matched.is_(True))
    elif matched == "0":
        client_filters.append(Sale.matched.is_(False))

    clients_q = db.query(Sale.client).distinct()
    if client_filters:
        clients_q = clients_q.filter(*client_filters)

    all_clients = [c[0] for c in clients_q.order_by(Sale.client) if c[0]]

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

    filters = []

    if not city:
        return JSONResponse(
            {"labels": [], "series": [], "message": "Выберите нужный город"}
        )

    if city:
        filters.append(Sale.city == city)
    if months:
        filters.append(Sale.month.in_(months))
    if client:
        filters.append(Sale.client == client)
    if sale_type:
        filters.append(Sale.type == sale_type)
    elif sale_types:
        filters.append(Sale.type.in_(sale_types))
    if matched == "1":
        filters.append(Sale.matched.is_(True))
    elif matched == "0":
        filters.append(Sale.matched.is_(False))

    def _fmt(m: str) -> str:
        return templates.env.filters["format_month"](m)

    if group == "type":
        q = db.query(
            Sale.month.label("month"),
            Sale.type.label("series"),
            func.sum(Sale.qty).label("qty"),
            func.sum(Sale.weight).label("weight"),
            func.count(func.distinct(Sale.sku)).label("unique_sku"),
            func.count(func.distinct(Sale.client)).label("unique_clients"),
        )

        if filters:
            q = q.filter(*filters)

        q = q.group_by(Sale.month, Sale.type).order_by(Sale.month, Sale.type)
        rows = q.all()

        month_list = sorted({r.month for r in rows if r.month}, key=month_sort_key)
        labels = [_fmt(m) for m in month_list]

        series_names = sorted({r.series for r in rows if r.series})
        data_map = {
            s: {
                m: {"qty": 0, "weight": 0, "unique_sku": 0, "unique_clients": 0}
                for m in month_list
            }
            for s in series_names
        }

        for r in rows:
            if not r.month or not r.series:
                continue

            data_map[r.series][r.month] = {
                "qty": float(r.qty or 0),
                "weight": float(r.weight or 0),
                "unique_sku": int(r.unique_sku or 0),
                "unique_clients": int(r.unique_clients or 0),
            }

        series = []
        for s in series_names:
            series.append(
                {
                    "name": s,
                    "qty": [data_map[s][m]["qty"] for m in month_list],
                    "weight": [data_map[s][m]["weight"] for m in month_list],
                    "unique_sku": [data_map[s][m]["unique_sku"] for m in month_list],
                    "unique_clients": [
                        data_map[s][m]["unique_clients"] for m in month_list
                    ],
                }
            )

        return JSONResponse({"labels": labels, "series": series})

    q = db.query(
        Sale.month.label("month"),
        Sale.type.label("type"),
        func.sum(Sale.qty).label("qty"),
        func.sum(Sale.weight).label("weight"),
        func.count(func.distinct(Sale.sku)).label("unique_sku"),
        func.count(func.distinct(Sale.client)).label("unique_clients"),
    )

    if filters:
        q = q.filter(*filters)

    q = q.group_by(Sale.month, Sale.type)
    rows = q.all()

    month_list = sorted({r.month for r in rows if r.month}, key=month_sort_key)
    type_list = sorted({r.type for r in rows if r.type})

    labels = [_fmt(m) for m in month_list]

    data = {
        m: {
            "qty": 0,
            "weight": 0,
            "unique_sku": 0,
            "unique_clients": 0,
            "types": {t: {"sku": 0, "clients": 0} for t in type_list},
        }
        for m in month_list
    }

    for r in rows:
        if not r.month:
            continue

        data[r.month]["qty"] += float(r.qty or 0)
        data[r.month]["weight"] += float(r.weight or 0)
        data[r.month]["unique_sku"] += int(r.unique_sku or 0)
        data[r.month]["unique_clients"] += int(r.unique_clients or 0)

        if r.type:
            data[r.month]["types"][r.type]["sku"] += int(r.unique_sku or 0)
            data[r.month]["types"][r.type]["clients"] += int(r.unique_clients or 0)

    series = [
        {
            "name": "Итого",
            "qty": [data[m]["qty"] for m in month_list],
            "weight": [data[m]["weight"] for m in month_list],
            "unique_sku": [data[m]["unique_sku"] for m in month_list],
            "unique_clients": [data[m]["unique_clients"] for m in month_list],
            "sku_per_client": [
                (
                    (data[m]["unique_sku"] / data[m]["unique_clients"])
                    if data[m]["unique_clients"]
                    else 0
                )
                for m in month_list
            ],
            "clients_by_type": {
                t: [data[m]["types"][t]["clients"] for m in month_list]
                for t in type_list
            },
            "sku_by_type": {
                t: [data[m]["types"][t]["sku"] for m in month_list] for t in type_list
            },
            "sku_per_client_by_type": {
                t: [
                    (
                        (data[m]["types"][t]["sku"] / data[m]["types"][t]["clients"])
                        if data[m]["types"][t]["clients"]
                        else 0
                    )
                    for m in month_list
                ]
                for t in type_list
            },
        }
    ]

    return JSONResponse(
        {
            "labels": labels,
            "series": series,
        }
    )


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

    q = db.query(
        Sale.name.label("name"),
        Sale.sku.label("sku"),
        func.sum(Sale.qty).label("qty"),
        func.sum(Sale.weight).label("weight"),
    ).filter(
        Sale.city == city,
        Sale.client == client,
        Sale.type == sale_type,
    )

    if months:
        q = q.filter(Sale.month.in_(months))

    if matched == "1":
        q = q.filter(Sale.matched.is_(True))
    elif matched == "0":
        q = q.filter(Sale.matched.is_(False))

    q = q.group_by(Sale.name, Sale.sku).order_by(Sale.name)
    rows = q.all()

    summary = None
    if rows:
        summary = {
            "nomenclatures": len(rows),
            "unique_sku": len({r.sku for r in rows if r.sku}),
            "total_qty": float(sum(r.qty or 0 for r in rows)),
            "total_weight": float(sum(r.weight or 0 for r in rows)),
        }

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
