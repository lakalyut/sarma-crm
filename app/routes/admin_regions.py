from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.status import HTTP_302_FOUND

from ..auth_deps import require_admin
from ..auth_models import User
from ..database import get_db
from ..render import render
from ..services import city_regions_service as svc
from ..services.sales_options_service import get_cities

router = APIRouter(prefix="/admin/regions", tags=["admin-regions"])


@router.get("")
def regions_page(
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    regions = svc.get_regions(db)
    city_region_map = svc.get_city_region_map(db)

    return render(
        request,
        "admin/regions.html",
        {
            "title": "Регионы — Пульс",
            "regions": regions,
            "cities": get_cities(db),
            "city_region_map": city_region_map,
        },
    )


@router.post("")
async def regions_save(
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    form = await request.form()
    cities = get_cities(db)

    assignments = {}
    for city in cities:
        raw_value = (form.get(f"region_{city}") or "").strip()
        assignments[city] = int(raw_value) if raw_value else None

    svc.save_city_assignments(db, assignments)

    return RedirectResponse("/admin/regions", status_code=HTTP_302_FOUND)


@router.post("/new")
def region_new(
    name: str = Form(...),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    svc.add_region(db, name)
    return RedirectResponse("/admin/regions", status_code=HTTP_302_FOUND)
