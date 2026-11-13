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
    SKU_STATUS_DEFAULTS,
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
    "Период анализа ABC / XYZ клиентов": {
        "client_segments_months": "Длина периода по умолчанию, мес.",
    },
    "Статусы клиентов": {
        "status_window_months": "Минимальная глубина истории по умолчанию, мес.",
        "new_client_months": "Период статуса «Новый» с первой закупки, мес.",
        "lost_months": "Месяцев без закупок подряд для статуса «Потерян»",
        "unstable_gap_months": "Минимальный перерыв между закупками для статуса «Нестабильный», мес.",
    },
    "Статусы товаров у клиента": {
        "sku_new_client_months": "Период статуса «Новый» с первой закупки товара, мес.",
        "sku_lost_months": "Месяцев без закупок товара подряд для статуса «Потерян»",
        "sku_unstable_gap_months": "Минимальный перерыв между закупками товара для статуса «Нестабильный», мес.",
    },
    "ABC клиентов по весу отгрузок": {
        "client_abc_a": "Целевая доля веса группы A, %",
        "client_abc_b": "Целевая доля веса групп A и B вместе, %",
    },
    "ABC городов и вкусов по весу": {
        "weight_abc_a": "Верхняя граница доли веса для A, %",
        "weight_abc_b": "Верхняя граница доли веса для A и B вместе, %",
    },
    "XYZ клиентов по колебаниям объёма": {
        "xyz_cv_x": "Максимальный коэффициент вариации для X, %",
        "xyz_cv_y": "Максимальный коэффициент вариации для Y, %",
    },
    "XYZ клиентов по регулярности закупок": {
        "xyz_presence_x": "Минимальная доля месяцев с закупками для X, %",
        "xyz_presence_y": "Минимальная доля месяцев с закупками для Y, %",
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
            "group_notes": {
                "Период анализа ABC / XYZ клиентов": (
                    "Начальный выбор на вкладке «Клиенты → ABC / XYZ». "
                    "В период попадают только загруженные месяцы. В отчёте можно выбрать другие месяцы."
                ),
                "Статусы клиентов": "Используются на главной и в списке клиентов.",
                "Статусы товаров у клиента": (
                    "Применяются к отдельным товарам (SKU) в карточке клиента "
                    "и в амбассадорском отчёте."
                ),
                "ABC клиентов по весу отгрузок": (
                    "Определяет первую букву класса на вкладке «Клиенты → ABC / XYZ». "
                    "Клиенты идут от большего веса к меньшему. Клиент, на котором "
                    "достигнут порог, входит в группу, которая набирала эту долю."
                ),
                "ABC городов и вкусов по весу": (
                    "Определяет буквы A, B и C в рейтингах «Топ городов» и «Топ вкусов» на главной. "
                    "Доля накапливается по мере добавления городов или вкусов от большего веса к меньшему."
                ),
                "XYZ клиентов по колебаниям объёма": (
                    "Определяет вторую букву класса в режиме «Колебания объёма» на вкладке "
                    "«Клиенты → ABC / XYZ». Чем сильнее меняется вес отгрузок по месяцам, "
                    "тем выше коэффициент вариации. Значения выше порога Y относятся к Z."
                ),
                "XYZ клиентов по регулярности закупок": (
                    "Определяет вторую букву класса в режиме «Наличие закупок» на вкладке "
                    "«Клиенты → ABC / XYZ». Если доля выбранных месяцев с закупками "
                    "ниже порога Y, присваивается Z при достаточной истории."
                ),
            },
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
                *SKU_STATUS_DEFAULTS,
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
