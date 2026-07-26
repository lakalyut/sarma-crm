from datetime import datetime

MONTHS_RU_ORDER = {
    "январь": 1,
    "февраль": 2,
    "март": 3,
    "апрель": 4,
    "май": 5,
    "июнь": 6,
    "июль": 7,
    "август": 8,
    "сентябрь": 9,
    "октябрь": 10,
    "ноябрь": 11,
    "декабрь": 12,
}


def parse_month(value: str) -> tuple[int, int] | None:
    """Разбирает месяц из Sale.month в (год, номер_месяца) — поддерживает
    оба формата, встречающихся в данных: ISO 'YYYY-MM-01' и уже
    отформатированное 'Месяц Год' (напр. 'Май 2026', так грузятся
    некоторые города при импорте). None, если не разобрать ни так, ни так."""
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(str(value))
        return (dt.year, dt.month)
    except (TypeError, ValueError):
        pass

    parts = str(value).strip().split()
    if len(parts) < 2:
        return None

    month_name = parts[0].strip().lower()
    year_part = parts[-1].strip()

    if month_name not in MONTHS_RU_ORDER:
        return None

    try:
        year_num = int(year_part)
    except ValueError:
        return None

    return (year_num, MONTHS_RU_ORDER[month_name])


def month_sort_key(value: str):
    return parse_month(value) or (9999, 12)
