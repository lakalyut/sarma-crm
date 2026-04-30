from collections import defaultdict

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Sale
from ..render import render
from ..utils.dates import month_sort_key

router = APIRouter()


def sku_expr():
    return func.coalesce(Sale.sku, Sale.raw_sku, Sale.name, Sale.raw_name)


@router.get("/analytics/ambassadors")
def analytics_ambassadors(
    request: Request,
    db: Session = Depends(get_db),
):
    selected_city = (request.query_params.get("city") or "").strip()
    selected_months = request.query_params.getlist("months")
    selected_clients = request.query_params.getlist("clients")

    cities = [r[0] for r in db.query(Sale.city).distinct().order_by(Sale.city) if r[0]]

    months_query = db.query(Sale.month).filter(Sale.month.isnot(None))
    if selected_city:
        months_query = months_query.filter(Sale.city == selected_city)

    all_months = [r[0] for r in months_query.distinct().all() if r[0]]
    all_months = sorted(all_months, key=month_sort_key, reverse=True)

    clients_query = db.query(Sale.client).filter(Sale.client.isnot(None))
    if selected_city:
        clients_query = clients_query.filter(Sale.city == selected_city)

    all_clients = [
        r[0] for r in clients_query.distinct().order_by(Sale.client).all() if r[0]
    ]

    selected_months = [m for m in selected_months if m in all_months]

    if selected_months:
        selected_months = sorted(selected_months, key=month_sort_key)
    else:
        selected_months = sorted(all_months, key=month_sort_key)

    selected_clients = [c for c in selected_clients if c in all_clients]

    report = {"months": [], "clients": []}

    if selected_city and selected_months and selected_clients:
        sales_rows = (
            db.query(
                Sale.client,
                Sale.month,
                Sale.weight,
                sku_expr().label("sku_key"),
            )
            .filter(
                Sale.city == selected_city,
                Sale.month.in_(selected_months),
                Sale.client.in_(selected_clients),
            )
            .all()
        )

        unique_sku_by_client_month = defaultdict(lambda: defaultdict(set))
        weight_by_client_month = defaultdict(lambda: defaultdict(float))
        sku_weight_by_client = defaultdict(
            lambda: defaultdict(lambda: defaultdict(float))
        )
        unique_sku_total_by_client = defaultdict(set)
        weight_total_by_client = defaultdict(float)

        for row in sales_rows:
            client = row.client or "Без клиента"
            month = row.month or ""
            weight = float(row.weight or 0)
            sku_key_value = (row.sku_key or "").strip()

            weight_by_client_month[client][month] += weight
            weight_total_by_client[client] += weight

            if sku_key_value:
                unique_sku_by_client_month[client][month].add(sku_key_value)
                unique_sku_total_by_client[client].add(sku_key_value)
                sku_weight_by_client[client][sku_key_value][month] += weight

        ordered_clients = selected_clients

        for client in ordered_clients:
            sku_summary = []
            weight_summary = []

            for month in selected_months:
                sku_summary.append(
                    len(unique_sku_by_client_month[client].get(month, set()))
                )
                weight_summary.append(
                    round(weight_by_client_month[client].get(month, 0.0), 2)
                )

            sku_details = []
            client_skus = sorted(sku_weight_by_client[client].keys())

            for sku_name in client_skus:
                months_data = []
                total = 0.0

                for month in selected_months:
                    value = round(
                        sku_weight_by_client[client][sku_name].get(month, 0.0), 2
                    )
                    months_data.append(value)
                    total += value

                sku_details.append(
                    {
                        "sku": sku_name,
                        "months_data": months_data,
                        "total": round(total, 2),
                    }
                )

            report["clients"].append(
                {
                    "name": client,
                    "sku_total": len(unique_sku_total_by_client[client]),
                    "weight_total": round(weight_total_by_client[client], 2),
                    "expanded": False,
                    "summary": {
                        "sku": sku_summary,
                        "weight": weight_summary,
                    },
                    "sku_details": sku_details,
                }
            )

        report["months"] = selected_months

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
