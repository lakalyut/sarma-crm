import json
import os
from datetime import datetime

from fastapi.templating import Jinja2Templates

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

MONTHS_RU = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}


def format_month(value: str):
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    month_name = MONTHS_RU.get(dt.month, "")
    return f"{month_name} {dt.year}"


def format_month_list(value):
    """Сворачивает список месяцев ('YYYY-MM-01') в компактную строку — тот
    же формат, что и закрытый вид мультиселекта в checkbox_multiselect.js:
    <=3 месяцев — список через запятую; >3 подряд идущих — диапазон
    «первый – последний»; >3 вразнобой — «первые 3, +N»."""
    if not value:
        return ""

    months = sorted(value)

    if len(months) <= 3:
        return ", ".join(format_month(m) for m in months)

    def next_month(m):
        dt = datetime.fromisoformat(m)
        year = dt.year + dt.month // 12
        month = dt.month % 12 + 1
        return f"{year:04d}-{month:02d}-01"

    try:
        is_contiguous = all(
            next_month(months[i]) == months[i + 1] for i in range(len(months) - 1)
        )
    except (TypeError, ValueError):
        is_contiguous = False

    if is_contiguous:
        return f"{format_month(months[0])} – {format_month(months[-1])}"

    labels = [format_month(m) for m in months]
    return ", ".join(labels[:3]) + f" +{len(labels) - 3}"


def format_month_short(value: str):
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    return MONTHS_RU.get(dt.month, "")[:3]


def group_months_by_year(all_months, selected_months=None):
    """Группирует уже отсортированный (reverse-chronological) список месяцев
    по году, сохраняя порядок первого появления. Возвращает список
    (год, месяцы_года, кол-во_выбранных_в_этом_году) — под аккордеон
    выбора периода (год — заголовок, месяцы — сетка)."""
    selected_set = set(selected_months or [])
    years: dict[str, list[str]] = {}

    for m in all_months or []:
        year = m[:4]
        years.setdefault(year, []).append(m)

    return [
        (year, months, sum(1 for m in months if m in selected_set))
        for year, months in years.items()
    ]


def tojson_filter(value):
    return json.dumps(value)


def format_ru_number(value, digits: int = 0) -> str:
    """Число в формате ru-RU: пробел — разделитель тысяч, запятая — дробная часть."""
    value = float(value or 0)
    formatted = f"{value:,.{digits}f}"
    return formatted.replace(",", "\x00").replace(".", ",").replace("\x00", " ")


templates.env.filters["format_month"] = format_month
templates.env.filters["format_month_short"] = format_month_short
templates.env.filters["format_month_list"] = format_month_list
templates.env.filters["group_months_by_year"] = group_months_by_year
templates.env.filters["tojson"] = tojson_filter
templates.env.filters["format_ru_number"] = format_ru_number
