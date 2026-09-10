"""Несопоставленные строки продаж — ручная доводка после импорта:
сопоставить с товаром (строка уходит в актуальные продажи города),
поправить поля или удалить. См. `services/unmatched_service.py`."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.status import HTTP_303_SEE_OTHER

from ..auth_deps import require_admin
from ..database import get_db
from ..models import Product, Sale
from ..render import render
from ..services.sales_options_service import get_cities
from ..services.unmatched_service import (
    active_products,
    delete_sale,
    match_sale_to_product,
    product_label,
    unmatch_sale,
    update_sale_fields,
)

router = APIRouter(prefix="/admin/unmatched", tags=["admin-unmatched"])

_LIST_URL = "/admin/unmatched"


def _products_ctx(db: Session) -> dict:
    products = active_products(db)
    return {
        "products": [{"id": p.id, "label": product_label(p)} for p in products],
        # label → id для JS (выбор в <datalist> отдаёт только строку-значение)
        "product_id_by_label": {product_label(p): p.id for p in products},
    }


@router.get("")
def unmatched_list(
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    rows = db.query(Sale).filter(Sale.matched.is_(False)).order_by(Sale.id.desc()).all()
    return render(
        request,
        "analytics/unmatched.html",
        {"title": "Несопоставленные — Пульс", "items": rows, **_products_ctx(db)},
    )


@router.post("/{sale_id}/match")
def unmatched_match(
    sale_id: int,
    product_id: int = Form(...),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    sale = db.get(Sale, sale_id)
    product = db.get(Product, product_id)
    if sale and product and product.is_active:
        match_sale_to_product(db, sale, product)
    return RedirectResponse(_LIST_URL, status_code=HTTP_303_SEE_OTHER)


@router.post("/{sale_id}/delete")
def unmatched_delete(
    sale_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    sale = db.get(Sale, sale_id)
    if sale:
        delete_sale(db, sale)
    return RedirectResponse(_LIST_URL, status_code=HTTP_303_SEE_OTHER)


@router.get("/{sale_id}/edit")
def unmatched_edit_form(
    sale_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    sale = db.get(Sale, sale_id)
    if not sale:
        return RedirectResponse(_LIST_URL, status_code=HTTP_303_SEE_OTHER)

    current_product = db.get(Product, sale.product_id) if sale.product_id else None
    return render(
        request,
        "analytics/unmatched_edit.html",
        {
            "title": "Несопоставленная строка — Пульс",
            "sale": sale,
            "cities": get_cities(db),
            "current_product_label": (
                product_label(current_product) if current_product else ""
            ),
            **_products_ctx(db),
        },
    )


@router.post("/{sale_id}/edit")
def unmatched_edit_submit(
    sale_id: int,
    request: Request,
    city: str = Form(""),
    month: str = Form(""),
    sale_type: str = Form(""),
    client: str = Form(""),
    qty: str = Form("0"),
    weight: str = Form("0"),
    product_id: str = Form(""),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    sale = db.get(Sale, sale_id)
    if not sale:
        return RedirectResponse(_LIST_URL, status_code=HTTP_303_SEE_OTHER)

    update_sale_fields(
        db,
        sale,
        city=city,
        month=month,
        sale_type=sale_type,
        client=client,
        qty=qty,
        weight=weight,
    )

    product = None
    if product_id.strip().isdigit():
        product = db.get(Product, int(product_id))

    if product and product.is_active:
        match_sale_to_product(db, sale, product)
    elif sale.matched:
        # товар убрали из выбора — строка снова несопоставленная
        unmatch_sale(db, sale)

    return RedirectResponse(_LIST_URL, status_code=HTTP_303_SEE_OTHER)
