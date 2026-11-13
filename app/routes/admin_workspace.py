from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..auth_deps import require_admin
from ..auth_models import User
from ..database import get_db
from ..models import AnalyticsSettings
from ..render import render
from ..services.admin_workspace_service import recent_imports
from ..services.analytics_settings_service import (
    DEFAULTS,
    MATCHING_DEFAULTS,
    get_analytics_settings,
    get_matching_settings,
)

router = APIRouter()


@router.get("/admin")
def admin_home(
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return render(
        request,
        "admin/home.html",
        {
            "title": "Администрирование — Пульс",
            "recent_imports": recent_imports(db, limit=5),
        },
    )


_SETTING_GROUPS = {
    "ABC/XYZ клиентов · период": {"client_segments_months": "Месяцев по умолчанию"},
    "Статусы клиентов и SKU · месяцы": {
        "status_window_months": "Окно расчёта статусов клиентов по умолчанию",
        "new_client_months": "Период статуса «Новый»",
        "lost_months": "Месяцев без продаж до статуса «Потерян»",
        "unstable_gap_months": "Минимальный разрыв между продажами для статуса «Нестабильный»",
    },
    "ABC клиентов · накопленная доля, %": {
        "client_abc_a": "Граница A",
        "client_abc_b": "Граница B",
    },
    "ABC по весу на главной · накопленная доля, %": {
        "weight_abc_a": "Граница A",
        "weight_abc_b": "Граница B",
    },
    "XYZ по объёму · коэффициент вариации, %": {
        "xyz_cv_x": "Максимум для X",
        "xyz_cv_y": "Максимум для Y",
    },
    "XYZ по регулярности · месяцы с закупками, %": {
        "xyz_presence_x": "Минимум для X",
        "xyz_presence_y": "Минимум для Y",
    },
}


@router.get("/admin/analytics-settings")
def analytics_settings(
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return _settings_form(request, get_analytics_settings(db))


def _settings_form(request, values, error=None):
    return render(
        request,
        "admin/analytics_settings.html",
        {
            "title": "Параметры аналитики — Пульс",
            "groups": _SETTING_GROUPS,
            "values": values,
            "error": error,
        },
    )


@router.post("/admin/analytics-settings")
async def save_analytics_settings(
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    form = await request.form()
    values = {key: str(form.get(key, "")) for key in DEFAULTS}
    if form.get("action") == "reset":
        settings = {}
    else:
        try:
            settings = {key: int(value) for key, value in values.items()}
            if not 1 <= settings["client_segments_months"] <= 120:
                raise ValueError
            for key in (
                "status_window_months",
                "new_client_months",
                "lost_months",
                "unstable_gap_months",
            ):
                if settings[key] < 1:
                    raise ValueError
            for low, high, minimum, maximum in (
                ("client_abc_a", "client_abc_b", 1, 99),
                ("weight_abc_a", "weight_abc_b", 1, 99),
                ("xyz_cv_x", "xyz_cv_y", 0, None),
                ("xyz_presence_y", "xyz_presence_x", 0, 100),
            ):
                if not minimum <= settings[low] < settings[high]:
                    raise ValueError
                if maximum is not None and settings[high] > maximum:
                    raise ValueError
        except ValueError:
            return _settings_form(
                request, values, "Проверьте диапазоны и порядок границ."
            )

    db.merge(AnalyticsSettings(id=1, values=settings))
    db.commit()
    return RedirectResponse("/admin/analytics-settings?notice=saved", status_code=303)


@router.api_route("/admin/matching-settings", methods=["GET", "POST"])
async def matching_settings(
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    values = get_matching_settings(db)
    error = None
    if request.method == "POST":
        form = await request.form()
        values = {key: str(form.get(key, "")) for key in MATCHING_DEFAULTS}
        try:
            settings = (
                {}
                if form.get("action") == "reset"
                else {key: int(value) for key, value in values.items()}
            )
            if settings and (
                not 0 <= settings["product_similarity"] <= 100
                or not 1
                <= settings["client_similarity_with_status"]
                <= settings["client_similarity"]
                <= 100
            ):
                raise ValueError
        except ValueError:
            error = "Проверьте диапазоны и порядок порогов."
        else:
            db.merge(AnalyticsSettings(id=2, values=settings))
            db.commit()
            return RedirectResponse(
                "/admin/matching-settings?notice=saved", status_code=303
            )
    return render(
        request,
        "admin/analytics_settings.html",
        {
            "title": "Импорт и ревизия",
            "description": "Пороги применяются к новым импортам и к поиску совпадений в ревизии клиентов.",
            "groups": {
                "Импорт номенклатуры": {
                    "product_similarity": "Минимальная оценка нечёткого совпадения, из 100"
                },
                "Ревизия клиентов": {
                    "client_similarity": "Минимальное сходство названий, %",
                    "client_similarity_with_status": "Минимальное сходство при совпадении по статусам, %",
                },
            },
            "values": values,
            "error": error,
        },
    )
