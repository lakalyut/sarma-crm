from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Dashboard, DashboardWidget
from .charts_service import get_charts_metrics_data
from .sale_filters import build_sale_filters

METRIC_CATALOG = [
    {
        "key": "qty",
        "label": "Количество",
        "summary_key": "total_qty",
        "series_key": "qty",
        "kind": "float",
        "unit": "",
    },
    {
        "key": "weight",
        "label": "Вес",
        "summary_key": "total_weight",
        "series_key": "weight",
        "kind": "float",
        "unit": "кг",
    },
    {
        "key": "unique_clients",
        "label": "Клиенты",
        "summary_key": "unique_clients",
        "series_key": "unique_clients",
        "kind": "int",
        "unit": "",
    },
    {
        "key": "unique_sku",
        "label": "Уникальных SKU",
        "summary_key": "unique_sku",
        "series_key": "unique_sku",
        "kind": "int",
        "unit": "",
    },
    {
        "key": "total_sku",
        "label": "Всего SKU",
        "summary_key": "total_sku",
        "series_key": "total_sku",
        "kind": "int",
        "unit": "",
    },
    {
        "key": "sku_per_client",
        "label": "SKU на клиента",
        "summary_key": "sku_per_client",
        "series_key": "sku_per_client",
        "kind": "float",
        "unit": "",
    },
]

METRIC_MAP = {m["key"]: m for m in METRIC_CATALOG}

WIDGET_DEFAULT_SIZE = {
    "metric_card": (4, 3),
    "chart": (6, 4),
}


# ---------------------------------------------------------------------------
# Дашборды
# ---------------------------------------------------------------------------


def get_user_dashboards(db: Session, user_id: int) -> list[Dashboard]:
    return (
        db.query(Dashboard)
        .filter(Dashboard.user_id == user_id)
        .order_by(Dashboard.id)
        .all()
    )


def get_active_dashboard(
    db: Session, user_id: int, dashboard_id: int | None = None
) -> Dashboard | None:
    if dashboard_id:
        d = (
            db.query(Dashboard)
            .filter(Dashboard.id == dashboard_id, Dashboard.user_id == user_id)
            .first()
        )
        if d:
            return d

    d = (
        db.query(Dashboard)
        .filter(Dashboard.user_id == user_id, Dashboard.is_default.is_(True))
        .first()
    )
    if d:
        return d

    return (
        db.query(Dashboard)
        .filter(Dashboard.user_id == user_id)
        .order_by(Dashboard.id)
        .first()
    )


def create_dashboard(db: Session, user_id: int, name: str) -> Dashboard:
    is_first = db.query(Dashboard).filter(Dashboard.user_id == user_id).count() == 0
    dashboard = Dashboard(
        user_id=user_id,
        name=name.strip() or "Новый дашборд",
        is_default=is_first,
    )
    db.add(dashboard)
    db.commit()
    db.refresh(dashboard)
    return dashboard


def rename_dashboard(db: Session, dashboard: Dashboard, name: str) -> None:
    name = name.strip()
    if name:
        dashboard.name = name
        db.commit()


def delete_dashboard(db: Session, dashboard: Dashboard) -> None:
    was_default = dashboard.is_default
    user_id = dashboard.user_id

    db.delete(dashboard)
    db.commit()

    if was_default:
        remaining = (
            db.query(Dashboard)
            .filter(Dashboard.user_id == user_id)
            .order_by(Dashboard.id)
            .first()
        )
        if remaining:
            remaining.is_default = True
            db.commit()


def set_default(db: Session, dashboard: Dashboard) -> None:
    db.query(Dashboard).filter(Dashboard.user_id == dashboard.user_id).update(
        {"is_default": False}
    )
    dashboard.is_default = True
    db.commit()


def update_filters(
    db: Session,
    dashboard: Dashboard,
    cities: list[str],
    clients: list[str],
    months: list[str],
    compare_mode: str,
    split_by: str = "city",
) -> None:
    dashboard.cities = cities
    dashboard.clients = clients
    dashboard.months = months
    dashboard.compare_mode = compare_mode if compare_mode == "split" else "aggregate"
    dashboard.split_by = split_by if split_by == "client" else "city"
    db.commit()


# ---------------------------------------------------------------------------
# Виджеты
# ---------------------------------------------------------------------------


def add_widget(
    db: Session,
    dashboard: Dashboard,
    metric: str,
    widget_type: str,
    chart_kind: str | None = None,
) -> DashboardWidget | None:
    if metric not in METRIC_MAP or widget_type not in WIDGET_DEFAULT_SIZE:
        return None

    max_y = (
        db.query(func.max(DashboardWidget.grid_y + DashboardWidget.grid_h))
        .filter(DashboardWidget.dashboard_id == dashboard.id)
        .scalar()
        or 0
    )
    w, h = WIDGET_DEFAULT_SIZE[widget_type]

    if widget_type == "metric_card" and dashboard.compare_mode == "split":
        axis = dashboard.clients if dashboard.split_by == "client" else dashboard.cities
        axis_count = len(axis or [])
        if axis_count > 1:
            h = 2 + axis_count * 3

    widget = DashboardWidget(
        dashboard_id=dashboard.id,
        metric=metric,
        widget_type=widget_type,
        chart_kind=chart_kind or ("line" if widget_type == "chart" else None),
        grid_x=0,
        grid_y=max_y,
        grid_w=w,
        grid_h=h,
    )
    db.add(widget)
    db.commit()
    db.refresh(widget)
    return widget


def remove_widget(db: Session, widget: DashboardWidget) -> None:
    db.delete(widget)
    db.commit()


def save_layout(db: Session, dashboard_id: int, positions: list[dict]) -> None:
    widgets = {
        w.id: w
        for w in db.query(DashboardWidget)
        .filter(DashboardWidget.dashboard_id == dashboard_id)
        .all()
    }

    for pos in positions:
        try:
            widget = widgets.get(int(pos["id"]))
        except (KeyError, TypeError, ValueError):
            continue

        if not widget:
            continue

        widget.grid_x = int(pos.get("x", widget.grid_x))
        widget.grid_y = int(pos.get("y", widget.grid_y))
        widget.grid_w = int(pos.get("w", widget.grid_w))
        widget.grid_h = int(pos.get("h", widget.grid_h))

    db.commit()


# ---------------------------------------------------------------------------
# Данные виджетов — переиспользуют clients_service/charts_service, никакой
# новой SQL-агрегации.
# ---------------------------------------------------------------------------


def _calc_delta(current: float, base: float | None) -> float | None:
    if not base:
        return None
    return (current - base) / base * 100


def _build_metric_trend(values: list, labels: list, label: str) -> dict:
    if not values or not labels:
        return {"label": label, "value": 0, "period": None, "deltas": []}

    last_index = len(values) - 1
    current = float(values[last_index] or 0)
    prev = float(values[last_index - 1] or 0) if last_index >= 1 else None
    first = float(values[0] or 0)
    average = sum(float(v or 0) for v in values) / len(values)

    deltas = [
        {
            "value": _calc_delta(current, prev),
            "text": (
                f"к прошлому месяцу ({labels[last_index - 1]})"
                if last_index >= 1
                else "к прошлому месяцу"
            ),
        },
        {"value": _calc_delta(current, average), "text": "к среднему за период"},
        {
            "value": _calc_delta(current, first),
            "text": f"к началу периода ({labels[0]})",
        },
    ]

    return {
        "label": label,
        "value": current,
        "period": labels[last_index],
        "deltas": deltas,
    }


def _compute_widget(
    db: Session, filters: list, widget_type: str, meta: dict, label: str
) -> dict:
    data = get_charts_metrics_data(db, filters, group="total")
    series = data["series"][0] if data["series"] else {}
    values = series.get(meta["series_key"], [])
    trend = _build_metric_trend(values, data["labels"], label)

    if widget_type == "metric_card":
        return trend

    return {
        "label": label,
        "labels": data["labels"],
        "values": values,
        "trend": trend,
    }


def get_widget_data(db: Session, dashboard: Dashboard, widget: DashboardWidget) -> dict:
    meta = METRIC_MAP.get(widget.metric)
    if not meta:
        return {
            "mode": "aggregate",
            "metric_label": widget.metric,
            "metric_kind": "float",
            "unit": "",
            "chart_kind": widget.chart_kind or "line",
            "label": widget.metric,
            "value": None,
        }

    cities = dashboard.cities or []
    clients = dashboard.clients or []
    months = dashboard.months or []
    split_by = dashboard.split_by or "city"

    if dashboard.compare_mode == "split" and split_by == "client" and len(clients) > 1:
        groups = [
            _compute_widget(
                db,
                build_sale_filters(cities=cities, client=client, months=months),
                widget.widget_type,
                meta,
                label=client,
            )
            for client in clients
        ]
        return {
            "mode": "split",
            "metric_label": meta["label"],
            "metric_kind": meta["kind"],
            "unit": meta.get("unit", ""),
            "chart_kind": widget.chart_kind or "line",
            "groups": groups,
        }

    if dashboard.compare_mode == "split" and split_by != "client" and len(cities) > 1:
        groups = [
            _compute_widget(
                db,
                build_sale_filters(city=city, clients=clients, months=months),
                widget.widget_type,
                meta,
                label=city,
            )
            for city in cities
        ]
        return {
            "mode": "split",
            "metric_label": meta["label"],
            "metric_kind": meta["kind"],
            "unit": meta.get("unit", ""),
            "chart_kind": widget.chart_kind or "line",
            "groups": groups,
        }

    filters = build_sale_filters(cities=cities, clients=clients, months=months)
    label = ", ".join(cities) if cities else "Все регионы"
    result = _compute_widget(db, filters, widget.widget_type, meta, label=label)
    return {
        "mode": "aggregate",
        "metric_label": meta["label"],
        "metric_kind": meta["kind"],
        "unit": meta.get("unit", ""),
        "chart_kind": widget.chart_kind or "line",
        **result,
    }
