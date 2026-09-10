from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.status import HTTP_302_FOUND

from ..auth_deps import require_admin
from ..auth_models import User
from ..database import get_db
from ..models import Product
from ..product_parser import (
    build_canonical_name,
    build_canonical_sku,
    normalize_text,
    parse_product_line,
)
from ..render import render
from ..services.nomenclature_review_service import (
    flavor_collision,
    product_drift_count,
    resync_product_sales,
)

router = APIRouter()


@router.get("/admin/products")
def products_list(
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    products = db.query(Product).order_by(Product.brand, Product.flavor).all()
    return render(
        request,
        "products/products_list.html",
        {"title": "Номенклатуры — Пульс", "products": products},
    )


@router.get("/admin/products/new")
def product_new_form(
    request: Request,
    _admin: User = Depends(require_admin),
):
    return render(
        request, "products/product_new.html", {"title": "Номенклатуры — Пульс"}
    )


@router.post("/admin/products/new")
def product_new(
    request: Request,
    category: str = Form("Табак для кальяна"),
    brand: str = Form(...),
    line: str = Form(""),
    flavor: str = Form(...),
    default_weight_g: int | None = Form(120),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
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
    db.refresh(p)

    # Тот же вкус у товара с другим брендом — вероятно опечатка в бренде
    # («Сарма» вместо «Сарма 360»). Не блокируем, показываем предупреждение
    # на карточке нового товара.
    if flavor_collision(db, p):
        return RedirectResponse(
            f"/admin/products/edit/{p.id}?dup=1", status_code=HTTP_302_FOUND
        )
    return RedirectResponse("/admin/products", status_code=HTTP_302_FOUND)


@router.get("/admin/products/import")
def products_import_form(
    request: Request,
    _admin: User = Depends(require_admin),
):
    return render(
        request, "products/products_import.html", {"title": "Номенклатуры — Пульс"}
    )


@router.post("/admin/products/import")
def products_import(
    request: Request,
    category: str = Form("Табак для кальяна"),
    default_weight_g: int | None = Form(120),
    lines: str = Form(...),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
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

    return render(
        request,
        "products/products_import.html",
        {
            "title": "Номенклатуры — Пульс",
            "message": f"Импортировано: {count} продуктов",
        },
    )


@router.get("/admin/products/edit/{product_id}")
def edit_product_form(
    product_id: int,
    request: Request,
    saved: int = 0,
    dup: int = 0,
    resynced: int = -1,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    product = db.query(Product).get(product_id)
    if not product:
        return {"error": "Product not found"}

    collision = flavor_collision(db, product) if (dup or saved) else None
    return render(
        request,
        "products/product_edit.html",
        {
            "title": f"{product.brand} — {product.flavor} — Пульс",
            "product": product,
            "drift_count": product_drift_count(db, product_id),
            "collision": collision,
            "saved": bool(saved),
            "resynced": resynced if resynced >= 0 else None,
        },
    )


@router.post("/admin/products/edit/{product_id}")
def edit_product(
    product_id: int,
    request: Request,
    category: str = Form(...),
    brand: str = Form(...),
    line: str = Form(""),
    flavor: str = Form(...),
    default_weight_g: int | None = Form(None),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    product = db.query(Product).get(product_id)
    if not product:
        return RedirectResponse("/admin/products", status_code=302)

    line_val = line.strip() or None

    product.category = category
    product.brand = brand
    product.line = line_val
    product.flavor = flavor
    product.default_weight_g = default_weight_g

    product.norm_brand = normalize_text(brand)
    product.norm_flavor = normalize_text(flavor)

    product.canonical_sku = build_canonical_sku(category, brand, line_val, flavor)
    product.canonical_name = build_canonical_name(
        product.canonical_sku, default_weight_g
    )

    db.commit()

    # На форму, а не в список: там плашка «продажи со старым названием —
    # пересинхронизировать?» и предупреждение о возможном дубле.
    return RedirectResponse(
        f"/admin/products/edit/{product_id}?saved=1", status_code=302
    )


@router.post("/admin/products/edit/{product_id}/resync-sales")
def resync_product(
    product_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    n = resync_product_sales(db, product_id)
    return RedirectResponse(
        f"/admin/products/edit/{product_id}?resynced={n}", status_code=302
    )
