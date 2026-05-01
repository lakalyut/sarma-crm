from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Sale
from ..utils.dates import month_sort_key


def sku_expr():
    return func.coalesce(Sale.sku, Sale.raw_sku, Sale.name, Sale.raw_name)


def normalize_selected_months(
    selected_months: list[str],
    all_months: list[str],
) -> list[str]:
    selected = [m for m in selected_months if m in all_months]

    if selected:
        return sorted(selected, key=month_sort_key)

    return sorted(all_months, key=month_sort_key)


def build_ambassadors_report(
    db: Session,
    selected_city: str,
    selected_months: list[str],
    selected_clients: list[str],
) -> dict:
    report = {"months": [], "clients": []}

    if not selected_city or not selected_months or not selected_clients:
        return report

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
    sku_weight_by_client = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
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

    for client in selected_clients:
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
            first_month = None

            for month in selected_months:
                value = round(sku_weight_by_client[client][sku_name].get(month, 0.0), 2)

                if value > 0 and first_month is None:
                    first_month = month

                months_data.append(value)
                total += value

                first_value = months_data[0] if months_data else 0
                last_value = months_data[-1] if months_data else 0

                active_month_indexes = [
                    index for index, value in enumerate(months_data) if value > 0
                ]

                has_sales = bool(active_month_indexes)
                first_active_index = active_month_indexes[0] if has_sales else None
                last_active_index = active_month_indexes[-1] if has_sales else None

                is_new = bool(
                    has_sales
                    and first_active_index is not None
                    and first_active_index > 0
                )

                missing_months_at_end = (
                    len(months_data) - 1 - last_active_index
                    if has_sales and last_active_index is not None
                    else 0
                )

                has_gaps_inside = False
                max_gap_before_last_sale = 0
                current_gap = 0

                if has_sales:
                    for index, value in enumerate(months_data):
                        if index > last_active_index:
                            break

                        if value == 0:
                            current_gap += 1
                            max_gap_before_last_sale = max(
                                max_gap_before_last_sale, current_gap
                            )
                        else:
                            current_gap = 0

                if not has_sales:
                    status = "empty"
                    status_label = "Нет продаж"
                elif last_value > 0:
                    if is_new and max_gap_before_last_sale >= 2:
                        status = "returned"
                        status_label = "Вернулся"
                    elif is_new:
                        status = "new"
                        status_label = f"Новый с {selected_months[first_active_index]}"
                    elif max_gap_before_last_sale >= 2:
                        status = "returned"
                        status_label = "Вернулся"
                    elif has_gaps_inside or max_gap_before_last_sale == 1:
                        status = "unstable"
                        status_label = "Нестабильный"
                    else:
                        status = "existing"
                        status_label = "Был с начала"
                else:
                    if missing_months_at_end >= 2:
                        status = "lost"
                        status_label = "Пропал"
                    else:
                        status = "risk"
                        status_label = "Под риском"

            delta_percent = None

            if first_value > 0:
                delta_percent = ((last_value - first_value) / first_value) * 100
            elif first_value == 0 and last_value > 0:
                delta_percent = 100

            sku_details.append(
                {
                    "sku": sku_name,
                    "months_data": months_data,
                    "total": round(total, 2),
                    "first_month": first_month,
                    "status": status,
                    "status_label": status_label,
                    "is_new": status == "new",
                    "is_lost": status == "lost",
                    "delta_percent": delta_percent,
                }
            )

        report["clients"].append(
            {
                "name": client,
                "sku_total": sum(sku_summary),
                "unique_sku_total": len(unique_sku_total_by_client[client]),
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
    return report
