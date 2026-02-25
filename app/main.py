import io
import os
from collections import defaultdict
from datetime import datetime

import pandas as pd
from fastapi import Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import Product, Sale
from .product_parser import (
    build_canonical_name,
    build_canonical_sku,
    extract_weight,
    match_product_by_flavor,
    normalize_text,
    parse_product_line,
)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Normalizer v3")

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


@app.get("/")
def root():
    return RedirectResponse("/admin/products")


# ---------- Products ----------


@app.get("/admin/products")
def products_list(request: Request, db: Session = Depends(get_db)):
    products = db.query(Product).order_by(Product.brand, Product.flavor).all()
    return templates.TemplateResponse(
        "products_list.html", {"request": request, "products": products}
    )


@app.get("/admin/products/new")
def product_new_form(request: Request):
    return templates.TemplateResponse("product_new.html", {"request": request})


@app.post("/admin/products/new")
def product_new(
    request: Request,
    category: str = Form("Табак для кальяна"),
    brand: str = Form(...),
    line: str = Form(""),
    flavor: str = Form(...),
    default_weight_g: int | None = Form(120),
    db: Session = Depends(get_db),
):
    line_val = line.strip() or None
    sku = build_canonical_sku(category, brand, line_val, flavor)
    name = build_canonical_name(sku, default_weight_g)
    p = Product(
        category=category,
        brand=brand,
        line=line_val,
        flavor=flavor,
        canonical_sku=sku,
        canonical_name=name,
        default_weight_g=default_weight_g,
        norm_brand=normalize_text(brand),
        norm_flavor=normalize_text(flavor),
        is_active=True,
    )
    db.add(p)
    db.commit()
    return RedirectResponse("/admin/products", status_code=303)


@app.get("/admin/products/import")
def products_import_form(request: Request):
    return templates.TemplateResponse("products_import.html", {"request": request})


@app.post("/admin/products/import")
def products_import(
    request: Request,
    category: str = Form("Табак для кальяна"),
    default_weight_g: int | None = Form(120),
    lines: str = Form(...),
    db: Session = Depends(get_db),
):
    count = 0
    for raw_line in lines.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        parsed = parse_product_line(raw_line)
        if not parsed:
            continue
        brand = parsed["brand"]
        line_val = parsed["line"]
        flavor = parsed["flavor"]
        sku = build_canonical_sku(category, brand, line_val, flavor)
        name = build_canonical_name(sku, default_weight_g)
        p = Product(
            category=category,
            brand=brand,
            line=line_val,
            flavor=flavor,
            canonical_sku=sku,
            canonical_name=name,
            default_weight_g=default_weight_g,
            norm_brand=normalize_text(brand),
            norm_flavor=normalize_text(flavor),
            is_active=True,
        )
        db.add(p)
        count += 1
    db.commit()
    return templates.TemplateResponse(
        "products_import.html",
        {"request": request, "message": f"Импортировано: {count} продуктов"},
    )


# ---------- XLSX import into sales ----------


@app.get("/import-xlsx")
def import_xlsx_form(request: Request):
    return templates.TemplateResponse("import_xlsx.html", {"request": request})


@app.post("/import-xlsx")
async def import_xlsx(
    request: Request,
    city: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    content = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(content))
    except Exception as e:
        return templates.TemplateResponse(
            "import_xlsx.html",
            {"request": request, "error": f"Ошибка чтения XLSX: {e}"},
        )

    required = ["Месяц", "Тип", "Клиент", "Номенклатура", "SKU", "Количество", "Вес"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return templates.TemplateResponse(
            "import_xlsx.html",
            {"request": request, "error": f'Нет колонок: {", ".join(missing)}'},
        )

    df["Количество"] = pd.to_numeric(df["Количество"], errors="coerce").fillna(0)
    df["Вес"] = pd.to_numeric(df["Вес"], errors="coerce").fillna(0)

    products = db.query(Product).filter(Product.is_active.is_(True)).all()

    imported = 0
    unmatched = 0

    for _, row in df.iterrows():
        raw_name = str(row["Номенклатура"])
        raw_sku = str(row["SKU"])
        p, score = match_product_by_flavor(raw_name, products)

        sale = Sale(
            city=city,
            month=str(row["Месяц"]),
            type=str(row["Тип"]),
            client=str(row["Клиент"]),
            raw_name=raw_name,
            raw_sku=raw_sku,
            qty=float(row["Количество"]),
            weight=float(row["Вес"]),
        )

        if p:
            sale.product_id = p.id
            w = extract_weight(raw_name) or p.default_weight_g
            sale.sku = p.canonical_sku
            sale.name = build_canonical_name(p.canonical_sku, w)
            sale.matched = True
        else:
            sale.matched = False
            unmatched += 1

        db.add(sale)
        imported += 1

    db.commit()
    return templates.TemplateResponse(
        "import_xlsx.html",
        {
            "request": request,
            "message": f"Импортировано строк: {imported}, не сопоставлено: {unmatched}",
        },
    )


@app.get("/analytics/clients")
def analytics_clients(
    request: Request,
    city: str | None = None,
    months: list[str] = Query(default=None),
    sale_types: list[str] = Query(default=None),
    matched: str | None = None,
    db: Session = Depends(get_db),
):
    # --- города для табов ---
    cities = [c[0] for c in db.query(Sale.city).distinct().order_by(Sale.city) if c[0]]

    # --- месяцы для выбранного города ---
    months_query = db.query(Sale.month).distinct()
    if city:
        months_query = months_query.filter(Sale.city == city)
    all_months = [m[0] for m in months_query.order_by(Sale.month) if m[0]]

    # --- типы точки для выбранного города ---
    types_query = db.query(Sale.type).distinct()
    if city:
        types_query = types_query.filter(Sale.city == city)
    all_types = [t[0] for t in types_query.order_by(Sale.type) if t[0]]

    # --- выбранные месяцы/типы пересекаем с доступными ---
    selected_months = months or []
    if all_months:
        selected_months = [m for m in selected_months if m in all_months]

    selected_types = sale_types or []
    if all_types:
        selected_types = [t for t in selected_types if t in all_types]

    # --- общий список фильтров для всех запросов ---
    filters = []
    if city:
        filters.append(Sale.city == city)
    if selected_months:
        filters.append(Sale.month.in_(selected_months))
    if selected_types:
        filters.append(Sale.type.in_(selected_types))

    if matched == "1":
        filters.append(Sale.matched.is_(True))
    elif matched == "0":
        filters.append(Sale.matched.is_(False))

    # --- основной запрос по строкам (type, client) ---
    q = db.query(
        Sale.type.label("type"),
        Sale.client.label("client"),
        func.sum(Sale.qty).label("qty"),
        func.sum(Sale.weight).label("weight"),
        func.count(func.distinct(Sale.sku)).label("sku_count"),
    )
    if filters:
        q = q.filter(*filters)

    q = q.group_by(Sale.type, Sale.client).order_by(Sale.type, Sale.client)
    rows = q.all()

    # --- агрегаты для верхнего среза: считаем НЕ из rows, а отдельными запросами ---
    unique_clients = 0
    unique_sku = 0
    total_qty = 0.0
    total_weight = 0.0
    total_sku = 0  # если он у тебя есть (сумма sku_count по клиентам) — можно считать отдельно, но это "общее SKU" в твоей логике

    # COUNT DISTINCT client
    client_q = db.query(func.count(func.distinct(Sale.client)))
    if filters:
        client_q = client_q.filter(*filters)
    unique_clients = int(client_q.scalar() or 0)

    # COUNT DISTINCT sku
    sku_q = db.query(func.count(func.distinct(Sale.sku)))
    if filters:
        sku_q = sku_q.filter(*filters)
    unique_sku = int(sku_q.scalar() or 0)

    # SUM qty/weight по всем строкам (из базы, а не из rows)
    sums_q = db.query(
        func.sum(Sale.qty).label("qty_sum"),
        func.sum(Sale.weight).label("weight_sum"),
    )
    if filters:
        sums_q = sums_q.filter(*filters)
    sums = sums_q.one()
    total_qty = float(sums.qty_sum or 0)
    total_weight = float(sums.weight_sum or 0)

    # total_sku — если ты сейчас считаешь "всего SKU" как сумму sku_count по клиентам:
    # это НЕ уникальные SKU, а "сколько разных SKU у каждого клиента суммарно" (SKU повторяются между клиентами)
    # если это именно то, что тебе нужно как "Всего SKU", то оставляем:
    if rows:
        total_sku = int(sum(r.sku_count or 0 for r in rows))
    else:
        total_sku = 0

    # --- карточки клиентов по типу точки ---
    type_cards = []
    if rows:
        type_counts = defaultdict(int)
        for r in rows:
            t = r.type or "—"
            type_counts[t] += 1
        type_cards = [{"type": t, "clients": cnt} for t, cnt in type_counts.items()]
        type_cards.sort(key=lambda x: str(x["type"]))

    summary = {
        "unique_clients": unique_clients,
        "total_qty": total_qty,
        "total_weight": total_weight,
        "unique_sku": unique_sku,
        "total_sku": total_sku,
        "sku_per_client": (
            (float(total_sku) / unique_clients) if unique_clients else 0.0
        ),
    }

    matched_flag = None
    if matched == "1":
        matched_flag = True
    elif matched == "0":
        matched_flag = False

    return templates.TemplateResponse(
        "clients_summary.html",
        {
            "request": request,
            "rows": rows,
            "cities": cities,
            "all_months": all_months,
            "all_types": all_types,
            "selected_city": city,
            "selected_months": selected_months,
            "selected_types": selected_types,
            "matched": matched_flag,
            "summary": summary,
            "type_cards": type_cards,
        },
    )


@app.get("/analytics/charts")
def analytics_charts(
    request: Request,
    city: str | None = None,
    months: list[str] = Query(default=None),
    sale_types: list[str] = Query(default=None),
    matched: str | None = None,
    group: str = "total",  # total | type
    db: Session = Depends(get_db),
):
    # --- города для табов ---
    cities = [c[0] for c in db.query(Sale.city).distinct().order_by(Sale.city) if c[0]]

    # --- месяцы для выбранного города ---
    months_q = db.query(Sale.month).distinct()
    if city:
        months_q = months_q.filter(Sale.city == city)
    all_months = [m[0] for m in months_q.order_by(Sale.month) if m[0]]

    # --- типы точки для выбранного города ---
    types_q = db.query(Sale.type).distinct()
    if city:
        types_q = types_q.filter(Sale.city == city)
    all_types = [t[0] for t in types_q.order_by(Sale.type) if t[0]]

    selected_months = months or []
    if all_months:
        selected_months = [m for m in selected_months if m in all_months]

    selected_types = sale_types or []
    if all_types:
        selected_types = [t for t in selected_types if t in all_types]

        # --- клиенты для выпадающего списка (по текущему городу, с учетом месяцев/типов/ matched) ---
    client_filters = []
    if city:
        client_filters.append(Sale.city == city)
    if selected_months:
        client_filters.append(Sale.month.in_(selected_months))
    if selected_types:
        client_filters.append(Sale.type.in_(selected_types))
    if matched == "1":
        client_filters.append(Sale.matched.is_(True))
    elif matched == "0":
        client_filters.append(Sale.matched.is_(False))

    clients_q = db.query(Sale.client).distinct()
    if client_filters:
        clients_q = clients_q.filter(*client_filters)

    all_clients = [c[0] for c in clients_q.order_by(Sale.client) if c[0]]

    matched_flag = None
    if matched == "1":
        matched_flag = True
    elif matched == "0":
        matched_flag = False

    return templates.TemplateResponse(
        "charts.html",
        {
            "request": request,
            "cities": cities,
            "all_months": all_months,
            "all_types": all_types,
            "selected_city": city,
            "selected_months": selected_months,
            "selected_types": selected_types,
            "matched": matched_flag,
            "group": group,
            "all_clients": all_clients,
            "selected_client": request.query_params.get("client") or "",
        },
    )


@app.get("/api/charts/metrics")
def api_charts_metrics(
    city: str | None = None,
    months: list[str] = Query(default=None),
    sale_types: list[str] = Query(default=None),
    matched: str | None = None,
    group: str = "total",  # total | type
    client: str | None = None,
    sale_type: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Возвращает динамику по месяцам:
    qty SUM, weight SUM, unique_sku COUNT DISTINCT, unique_clients COUNT DISTINCT
    group=total -> одна серия
    group=type  -> серии по типам точек
    """

    # базовые фильтры
    filters = []
    if city:
        filters.append(Sale.city == city)
    if months:
        filters.append(Sale.month.in_(months))
    if client:
        filters.append(Sale.client == client)
    if sale_type:
        filters.append(Sale.type == sale_type)
    elif sale_types:
        filters.append(Sale.type.in_(sale_types))
    if matched == "1":
        filters.append(Sale.matched.is_(True))
    elif matched == "0":
        filters.append(Sale.matched.is_(False))

    # helper: формат подписи месяца
    def _fmt(m: str) -> str:
        return format_month(m)  # твой jinja filter (уже есть)

    if group == "type":
        q = db.query(
            Sale.month.label("month"),
            Sale.type.label("series"),
            func.sum(Sale.qty).label("qty"),
            func.sum(Sale.weight).label("weight"),
            func.count(func.distinct(Sale.sku)).label("unique_sku"),
            func.count(func.distinct(Sale.client)).label("unique_clients"),
        )
        if filters:
            q = q.filter(*filters)
        q = q.group_by(Sale.month, Sale.type).order_by(Sale.month, Sale.type)
        rows = q.all()

        # ось X
        month_list = sorted({r.month for r in rows if r.month})
        labels = [_fmt(m) for m in month_list]

        # серии
        series_names = sorted({r.series for r in rows if r.series})
        data_map = {
            s: {
                m: {"qty": 0, "weight": 0, "unique_sku": 0, "unique_clients": 0}
                for m in month_list
            }
            for s in series_names
        }

        for r in rows:
            if not r.month or not r.series:
                continue
            data_map[r.series][r.month] = {
                "qty": float(r.qty or 0),
                "weight": float(r.weight or 0),
                "unique_sku": int(r.unique_sku or 0),
                "unique_clients": int(r.unique_clients or 0),
            }

        series = []
        for s in series_names:
            series.append(
                {
                    "name": s,
                    "qty": [data_map[s][m]["qty"] for m in month_list],
                    "weight": [data_map[s][m]["weight"] for m in month_list],
                    "unique_sku": [data_map[s][m]["unique_sku"] for m in month_list],
                    "unique_clients": [
                        data_map[s][m]["unique_clients"] for m in month_list
                    ],
                }
            )

        return JSONResponse({"labels": labels, "series": series})

    # group == total
    q = db.query(
        Sale.month.label("month"),
        func.sum(Sale.qty).label("qty"),
        func.sum(Sale.weight).label("weight"),
        func.count(func.distinct(Sale.sku)).label("unique_sku"),
        func.count(func.distinct(Sale.client)).label("unique_clients"),
    )
    if filters:
        q = q.filter(*filters)
    q = q.group_by(Sale.month).order_by(Sale.month)
    rows = q.all()

    month_list = [r.month for r in rows if r.month]
    labels = [_fmt(m) for m in month_list]

    series = [
        {
            "name": "Итого",
            "qty": [float(r.qty or 0) for r in rows],
            "weight": [float(r.weight or 0) for r in rows],
            "unique_sku": [int(r.unique_sku or 0) for r in rows],
            "unique_clients": [int(r.unique_clients or 0) for r in rows],
        }
    ]

    return JSONResponse({"labels": labels, "series": series})


@app.get("/analytics/client")
def analytics_client_detail(
    request: Request,
    city: str,
    client: str,
    sale_type: str,
    months: list[str] = Query(default=None),
    matched: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Детализация по клиенту:
    строки: Номенклатура + SKU
    показатели: SUM(Кол-во), SUM(Вес)
    + срез по клиенту (кол-во номенклатур, уникальные SKU, суммы).
    """

    q = db.query(
        Sale.name.label("name"),
        Sale.sku.label("sku"),
        func.sum(Sale.qty).label("qty"),
        func.sum(Sale.weight).label("weight"),
    ).filter(
        Sale.city == city,
        Sale.client == client,
        Sale.type == sale_type,
    )

    if months:
        q = q.filter(Sale.month.in_(months))

    if matched == "1":
        q = q.filter(Sale.matched.is_(True))
    elif matched == "0":
        q = q.filter(Sale.matched.is_(False))

    q = q.group_by(Sale.name, Sale.sku).order_by(Sale.name)

    rows = q.all()

    # ---- срез по клиенту ----
    summary = None
    if rows:
        # количество номенклатур (строк в таблице)
        nomenclatures_count = len(rows)
        # уникальные SKU по этому клиенту и фильтрам
        unique_sku = len({r.sku for r in rows if r.sku})
        # суммы
        total_qty = float(sum(r.qty or 0 for r in rows))
        total_weight = float(sum(r.weight or 0 for r in rows))

        summary = {
            "nomenclatures": nomenclatures_count,
            "unique_sku": unique_sku,
            "total_qty": total_qty,
            "total_weight": total_weight,
        }

    return templates.TemplateResponse(
        "client_detail.html",
        {
            "request": request,
            "rows": rows,
            "city": city,
            "client": client,
            "sale_type": sale_type,
            "months": months or [],
            "summary": summary,
        },
    )
