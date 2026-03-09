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


templates.env.filters["format_month"] = format_month
