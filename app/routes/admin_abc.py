from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.status import HTTP_302_FOUND

from ..auth_deps import require_admin
from ..auth_models import User
from ..database import get_db
from ..models import AbcSegment, Product, ProductAbcRating
from ..render import render
from ..services.abc_service import (
    ABC_CATEGORIES,
    add_segment,
    ensure_default_segments,
    get_abc_matrix_data,
)

router = APIRouter(prefix="/admin/abc", tags=["admin-abc"])


@router.get("")
def abc_matrix(
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    ensure_default_segments(db)
    data = get_abc_matrix_data(db)

    return render(
        request,
        "admin/abc_matrix.html",
        {
            "segments": data["segments"],
            "grouped_products": data["grouped_products"],
            "rating_map": data["rating_map"],
            "categories": ABC_CATEGORIES,
        },
    )


@router.post("")
async def abc_matrix_save(
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    form = await request.form()

    segments = db.query(AbcSegment).all()
    products = db.query(Product).filter(Product.is_active.is_(True)).all()

    existing_ratings = {
        (r.product_id, r.segment_id): r for r in db.query(ProductAbcRating).all()
    }

    for product in products:
        product.is_new = form.get(f"is_new_{product.id}") == "on"

        for segment in segments:
            field_name = f"category_{product.id}_{segment.id}"
            value = (form.get(field_name) or "").strip()

            key = (product.id, segment.id)
            existing = existing_ratings.get(key)

            if value:
                if existing:
                    existing.category = value
                else:
                    db.add(
                        ProductAbcRating(
                            product_id=product.id,
                            segment_id=segment.id,
                            category=value,
                        )
                    )
            elif existing:
                db.delete(existing)

    db.commit()

    return RedirectResponse("/admin/abc", status_code=HTTP_302_FOUND)


@router.post("/segments/new")
def abc_segment_new(
    name: str = Form(...),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    add_segment(db, name)
    return RedirectResponse("/admin/abc", status_code=HTTP_302_FOUND)
