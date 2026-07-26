import json
import os

from fastapi.templating import Jinja2Templates

from .utils.dates import parse_month

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
    """Форматирует месяц в "Месяц Год". Sale.month хранит два формата
    вперемешку — ISO 'YYYY-MM-01' и уже готовое 'Месяц Год' (некоторые
    города грузятся сразу в этом виде) — parse_month() из app/utils/dates.py
    разбирает оба; неразбираемое возвращаем как есть."""
    parsed = parse_month(value)
    if not parsed:
        return value
    year, month = parsed
    return f"{MONTHS_RU.get(month, '')} {year}"


def format_month_short(value: str):
    parsed = parse_month(value)
    if not parsed:
        return value
    _, month = parsed
    return MONTHS_RU.get(month, "")[:3]


def format_month_list(value):
    """Сворачивает список месяцев в компактную строку — тот же формат, что
    и закрытый вид мультиселекта в checkbox_multiselect.js: <=3 месяцев —
    список через запятую; >3 подряд идущих — диапазон «первый – последний»;
    >3 вразнобой — «первые 3, +N». Сортировка и проверка непрерывности —
    по разобранным (год, месяц), не по сырой строке (лексикографический
    порядок ISO-строк и "Месяц Год"-строк не совпадает)."""
    if not value:
        return ""

    months = sorted(value, key=lambda m: parse_month(m) or (9999, 12))

    if len(months) <= 3:
        return ", ".join(format_month(m) for m in months)

    keys = [parse_month(m) for m in months]

    def next_key(key):
        year, month = key
        return (year + month // 12, month % 12 + 1)

    is_contiguous = all(keys) and all(
        next_key(keys[i]) == keys[i + 1] for i in range(len(keys) - 1)
    )

    if is_contiguous:
        return f"{format_month(months[0])} – {format_month(months[-1])}"

    labels = [format_month(m) for m in months]
    return ", ".join(labels[:3]) + f" +{len(labels) - 3}"


def group_months_by_year(all_months, selected_months=None):
    """Группирует уже отсортированный (reverse-chronological) список месяцев
    по году, сохраняя порядок первого появления. Возвращает список
    (год, месяцы_года, кол-во_выбранных_в_этом_году) — под аккордеон
    выбора периода (год — заголовок, месяцы — сетка). Год — через
    parse_month() (ISO и "Месяц Год" оба поддержаны); неразбираемые значения
    уходят в один общий хвостовой бакет "—", не смешиваясь ни с реальными
    годами, ни друг с другом."""
    selected_set = set(selected_months or [])
    years: dict[str, list[str]] = {}

    for m in all_months or []:
        parsed = parse_month(m)
        year = str(parsed[0]) if parsed else ""
        years.setdefault(year, []).append(m)

    unknown = years.pop("", None)

    result = [
        (year, months, sum(1 for m in months if m in selected_set))
        for year, months in years.items()
    ]

    if unknown:
        result.append(("—", unknown, sum(1 for m in unknown if m in selected_set)))

    return result


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
