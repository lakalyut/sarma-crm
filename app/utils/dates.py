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


def month_sort_key(value: str):

    if not value:
        return (9999, 12)

    parts = str(value).strip().split()
    if len(parts) < 2:
        return (9999, 12)

    month_name = parts[0].strip().lower()
    year_part = parts[-1].strip()

    month_num = MONTHS_RU_ORDER.get(month_name, 12)

    try:
        year_num = int(year_part)
    except ValueError:
        year_num = 9999

    return (year_num, month_num)