"""ABC по объёму города и XYZ по общему календарному окну."""

import math
from collections import defaultdict
from datetime import date
from statistics import mean, pstdev

from sqlalchemy import case, func, or_

from ..models import Sale
from ..utils.dates import parse_month


def shift_month(month, offset):
    year, number = divmod(month[0] * 12 + month[1] - 1 + offset, 12)
    return year, number + 1


def month_value(month):
    return f"{month[0]:04d}-{month[1]:02d}"


def build_client_segments(db, city, *, length=6, end=None, complete=False, today=None):
    today = today or date.today()
    current = (today.year, today.month)
    valid_client = func.trim(Sale.client)
    positive = (
        (Sale.weight > 0)
        & (Sale.weight < float("inf"))
        & or_(Sale.qty.is_(None), Sale.qty >= 0)
    )
    groups = (
        db.query(
            valid_client.label("client"),
            Sale.month,
            func.sum(case((positive, Sale.weight), else_=0)).label("volume"),
            func.sum(case((or_(Sale.weight < 0, Sale.qty < 0), 1), else_=0)).label(
                "returns"
            ),
        )
        .filter(Sale.city == city)
        .group_by(valid_client, Sale.month)
        .all()
    )
    loaded = {
        parsed
        for row in groups
        if (parsed := parse_month(row.month)) and parsed < current
    }
    end = end or max(loaded, default=shift_month(current, -1))
    window = [shift_month(end, offset) for offset in range(1 - length, 1)]
    missing = [month for month in window if month not in loaded]
    volumes = defaultdict(lambda: defaultdict(float))
    first_seen = {}
    returns = invalid_months = 0
    for row in groups:
        month = parse_month(row.month)
        if month is None:
            invalid_months += 1
            continue
        if month > end:
            continue
        if month in window:
            returns += int(row.returns or 0)
        if not row.client or row.client.lower() == "nan":
            continue
        volume = float(row.volume or 0)
        if not math.isfinite(volume) or volume <= 0:
            continue
        volumes[row.client][month] += volume
        first_seen[row.client] = min(first_seen.get(row.client, month), month)

    rows = []
    for client, history in volumes.items():
        monthly = [history.get(month, 0) for month in window]
        total = sum(monthly)
        reason = ""
        if total == 0:
            reason = "inactive"
        elif missing:
            reason = "missing"
        elif invalid_months:
            reason = "invalid"
        elif first_seen[client] > window[0]:
            reason = "insufficient"
        elif not complete:
            reason = "unconfirmed"
        cv = pstdev(monthly) / mean(monthly) * 100 if not reason else None
        xyz = (
            ("X" if cv <= 25 else "Y" if cv <= 50 else "Z") if cv is not None else None
        )
        rows.append(
            {
                "client": client,
                "volume": total,
                "monthly": monthly,
                "active_months": sum(value > 0 for value in monthly),
                "first_seen": month_value(first_seen[client]),
                "cv": cv,
                "xyz": xyz,
                "abc": None,
                "reason": reason,
            }
        )
    rows.sort(key=lambda row: (-row["volume"], row["client"]))
    total = sum(row["volume"] for row in rows)
    cumulative = 0
    matrix = {a + x: {"count": 0, "share": 0} for a in "ABC" for x in "XYZ"}
    reasons = defaultdict(int)
    for row in rows:
        row["share"] = row["volume"] / total * 100 if total else 0
        if row["volume"] > 0:
            boundary = round(cumulative, 10)
            row["abc"] = "A" if boundary < 80 else "B" if boundary < 95 else "C"
            cumulative += row["share"]
        row["segment"] = row["abc"] + row["xyz"] if row["xyz"] else row["reason"]
        if row["xyz"]:
            matrix[row["segment"]]["count"] += 1
            matrix[row["segment"]]["share"] += row["share"]
        else:
            reasons[row["reason"]] += 1
    return {
        "rows": rows,
        "matrix": matrix,
        "reasons": dict(reasons),
        "total_volume": total,
        "active_clients": sum(row["volume"] > 0 for row in rows),
        "window": [month_value(month) for month in window],
        "end": month_value(end),
        "length": length,
        "complete": complete,
        "end_options": [month_value(month) for month in sorted(loaded, reverse=True)],
        "missing": [month_value(month) for month in missing],
        "returns": returns,
        "invalid_months": invalid_months,
    }
