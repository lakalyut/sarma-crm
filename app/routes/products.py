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

router = APIRouter()


@router.get("/admin/products")
def products_list(
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    products = db.query(Product).order_by(Product.brand, Product.flavor).all()
    return render(request, "products/products_list.html", {"products": products})


@router.get("/admin/products/new")
def product_new_form(
    request: Request,
    _admin: User = Depends(require_admin),
):
    return render(request, "products/product_new.html", {})


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

    return RedirectResponse("/admin/products", status_code=HTTP_302_FOUND)


@router.get("/admin/products/import")
def products_import_form(
    request: Request,
    _admin: User = Depends(require_admin),
):
    return render(request, "products/products_import.html", {})


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
        "products_import.html",
        {"message": f"Импортировано: {count} продуктов"},
    )


@router.get("/admin/products/edit/{product_id}")
def edit_product_form(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    product = db.query(Product).get(product_id)
    if not product:
        return {"error": "Product not found"}

    return render(request, "products/product_edit.html", {"product": product})


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

    return RedirectResponse("/admin/products", status_code=302)
