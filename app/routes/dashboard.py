from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.status import HTTP_302_FOUND, HTTP_404_NOT_FOUND

from ..auth_deps import require_user
from ..auth_models import User
from ..database import get_db
from ..models import Dashboard, DashboardWidget
from ..render import render
from ..services import dashboard_service as svc
from ..services.sales_options_service import get_cities, get_clients, get_months

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def dashboard_page(
    request: Request,
    id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_user),
):
    dashboards = svc.get_user_dashboards(db, _user.id)

    if not dashboards:
        svc.create_dashboard(db, _user.id, "Мой дашборд")
        dashboards = svc.get_user_dashboards(db, _user.id)

    active = svc.get_active_dashboard(db, _user.id, dashboard_id=id)

    widgets = []
    for widget in active.widgets:
        meta = svc.METRIC_MAP.get(widget.metric, {})
        entry = {"widget": widget, "metric_label": meta.get("label", widget.metric)}

        if widget.widget_type == "metric_card":
            entry["data"] = svc.get_widget_data(db, active, widget)

        widgets.append(entry)

    return render(
        request,
        "dashboard/dashboard.html",
        {
            "dashboards": dashboards,
            "active": active,
            "widgets": widgets,
            "metric_catalog": svc.METRIC_CATALOG,
            "cities": get_cities(db),
            "all_months": get_months(db),
            "all_clients": get_clients(db),
        },
    )


@router.post("/new")
def dashboard_new(
    name: str = Form("Новый дашборд"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_user),
):
    dashboard = svc.create_dashboard(db, _user.id, name)
    return RedirectResponse(f"/dashboard?id={dashboard.id}", status_code=HTTP_302_FOUND)


@router.post("/{dashboard_id}/rename")
def dashboard_rename(
    dashboard_id: int,
    name: str = Form(...),
    db: Session = Depends(get_db),
    _user: User = Depends(require_user),
):
    dashboard = (
        db.query(Dashboard)
        .filter(Dashboard.id == dashboard_id, Dashboard.user_id == _user.id)
        .first()
    )
    if dashboard:
        svc.rename_dashboard(db, dashboard, name)
    return RedirectResponse(f"/dashboard?id={dashboard_id}", status_code=HTTP_302_FOUND)


@router.post("/{dashboard_id}/delete")
def dashboard_delete(
    dashboard_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_user),
):
    dashboard = (
        db.query(Dashboard)
        .filter(Dashboard.id == dashboard_id, Dashboard.user_id == _user.id)
        .first()
    )
    if dashboard:
        svc.delete_dashboard(db, dashboard)
    return RedirectResponse("/dashboard", status_code=HTTP_302_FOUND)


@router.post("/{dashboard_id}/set-default")
def dashboard_set_default(
    dashboard_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_user),
):
    dashboard = (
        db.query(Dashboard)
        .filter(Dashboard.id == dashboard_id, Dashboard.user_id == _user.id)
        .first()
    )
    if dashboard:
        svc.set_default(db, dashboard)
    return RedirectResponse(f"/dashboard?id={dashboard_id}", status_code=HTTP_302_FOUND)


@router.post("/{dashboard_id}/filters")
async def dashboard_filters(
    dashboard_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _user: User = Depends(require_user),
):
    dashboard = (
        db.query(Dashboard)
        .filter(Dashboard.id == dashboard_id, Dashboard.user_id == _user.id)
        .first()
    )
    if dashboard:
        form = await request.form()
        svc.update_filters(
            db,
            dashboard,
            cities=form.getlist("cities"),
            clients=form.getlist("clients"),
            months=form.getlist("months"),
            compare_mode=form.get("compare_mode") or "aggregate",
            split_by=form.get("split_by") or "city",
        )
    return RedirectResponse(f"/dashboard?id={dashboard_id}", status_code=HTTP_302_FOUND)


@router.post("/{dashboard_id}/widgets")
def dashboard_add_widget(
    dashboard_id: int,
    metric: str = Form(...),
    widget_type: str = Form(...),
    chart_kind: str = Form("line"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_user),
):
    dashboard = (
        db.query(Dashboard)
        .filter(Dashboard.id == dashboard_id, Dashboard.user_id == _user.id)
        .first()
    )
    if dashboard:
        svc.add_widget(db, dashboard, metric, widget_type, chart_kind)
    return RedirectResponse(f"/dashboard?id={dashboard_id}", status_code=HTTP_302_FOUND)


@router.post("/{dashboard_id}/widgets/{widget_id}/delete")
def dashboard_delete_widget(
    dashboard_id: int,
    widget_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_user),
):
    widget = (
        db.query(DashboardWidget)
        .join(Dashboard, Dashboard.id == DashboardWidget.dashboard_id)
        .filter(
            DashboardWidget.id == widget_id,
            Dashboard.id == dashboard_id,
            Dashboard.user_id == _user.id,
        )
        .first()
    )
    if widget:
        svc.remove_widget(db, widget)
    return RedirectResponse(f"/dashboard?id={dashboard_id}", status_code=HTTP_302_FOUND)


@router.post("/{dashboard_id}/layout")
async def dashboard_layout(
    dashboard_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _user: User = Depends(require_user),
):
    dashboard = (
        db.query(Dashboard)
        .filter(Dashboard.id == dashboard_id, Dashboard.user_id == _user.id)
        .first()
    )
    if not dashboard:
        return JSONResponse({"ok": False}, status_code=HTTP_404_NOT_FOUND)

    payload = await request.json()
    svc.save_layout(db, dashboard_id, payload.get("positions", []))
    return JSONResponse({"ok": True})


@router.get("/{dashboard_id}/widgets/{widget_id}/data")
def dashboard_widget_data(
    dashboard_id: int,
    widget_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_user),
):
    dashboard = (
        db.query(Dashboard)
        .filter(Dashboard.id == dashboard_id, Dashboard.user_id == _user.id)
        .first()
    )
    if not dashboard:
        return JSONResponse({"error": "not found"}, status_code=HTTP_404_NOT_FOUND)

    widget = (
        db.query(DashboardWidget)
        .filter(
            DashboardWidget.id == widget_id,
            DashboardWidget.dashboard_id == dashboard_id,
        )
        .first()
    )
    if not widget:
        return JSONResponse({"error": "not found"}, status_code=HTTP_404_NOT_FOUND)

    return JSONResponse(svc.get_widget_data(db, dashboard, widget))
