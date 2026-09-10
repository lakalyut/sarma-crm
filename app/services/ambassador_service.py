"""Горизонт 13, Этап 3 — данные и создание визита в мини-аппе амбассадора.

Амбассадор привязан к одному конкретному городу (User.city — та же природа
поле, что Sale.city/Visit.city, не отдельная сущность), не к макро-региону —
поэтому все данные визита берутся строго по этому одному городу, без
разворачивания в список городов региона."""

from sqlalchemy.orm import Session

from ..auth_models import User
from ..models import AbcSegment, Product, ProductAbcRating, Visit, VisitProduct
from . import sales_options_service
from .abc_service import guess_default_segment

# «Цель визита» — быстрые варианты (чипы над текстовым полем формы визита).
# Список редактируется здесь; амбассадор может вписать и свою цель текстом.
VISIT_GOALS: list[str] = [
    "Прокур новинки",
    "Обучение по продукту",
]


def ambassador_display_name(user: User | None) -> str:
    if not user:
        return "—"
    name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return name or user.email


def _parse_count(raw, label: str) -> int:
    if raw is None or str(raw).strip() == "":
        raise ValueError(f"Укажите «{label}»")
    try:
        value = int(str(raw).strip())
    except ValueError:
        raise ValueError(f"«{label}» — это число") from None
    if value < 0:
        raise ValueError(f"«{label}» не может быть отрицательным")
    return value


def get_visit_options(db: Session, city: str) -> dict:
    clients = sales_options_service.get_clients(db, city=city)
    types = sales_options_service.get_types(db, city=city)

    segments = db.query(AbcSegment).order_by(AbcSegment.sort_order, AbcSegment.id).all()
    guessed_segment_by_type: dict[str, int] = {}
    for sale_type in types:
        segment = guess_default_segment(segments, sale_type)
        if segment:
            guessed_segment_by_type[sale_type] = segment.id

    needed_segment_ids = set(guessed_segment_by_type.values())
    abc_by_segment: dict[int, dict[int, str]] = {}
    if needed_segment_ids:
        ratings = (
            db.query(ProductAbcRating)
            .filter(ProductAbcRating.segment_id.in_(needed_segment_ids))
            .all()
        )
        for rating in ratings:
            abc_by_segment.setdefault(rating.segment_id, {})[
                rating.product_id
            ] = rating.category

    products = (
        db.query(Product)
        .filter(Product.is_active.is_(True))
        .order_by(Product.category, Product.brand, Product.flavor)
        .all()
    )

    return {
        "cities": [city],
        "clients_by_city": {city: clients},
        "types_by_city": {city: types},
        "guessed_segment_by_type": guessed_segment_by_type,
        "abc_by_segment": abc_by_segment,
        "visit_goals": VISIT_GOALS,
        "products": [
            {
                "id": p.id,
                "category": p.category,
                "brand": p.brand,
                "flavor": p.flavor,
                "name": p.canonical_name,
                "sku": p.canonical_sku,
            }
            for p in products
        ],
    }


def get_visit_months(db: Session, city: str | None = None) -> list[str]:
    """Месяцы, в которые были визиты (`Visit.created_at` → 'YYYY-MM-01').
    Вкладки «Анализ визита»/«Эффективность визита» строят пикер периода из
    объединения этого списка с `Sale.month`: визит текущего месяца иначе
    невиден — за него ещё нет импорта продаж, а месяц берётся из `Sale`."""
    query = db.query(Visit.created_at)
    if city:
        query = query.filter(Visit.city == city)
    months = {dt.strftime("%Y-%m-01") for (dt,) in query if dt}
    return sorted(months)


def get_visit_clients(db: Session, city: str | None = None) -> list[str]:
    """Клиенты, к которым были визиты — для дропдауна «Клиенты» на тех же
    вкладках (Sale-справочник клиентов не знает про точку, где визит был, а
    продажи ещё нет)."""
    query = db.query(Visit.client).filter(Visit.client.isnot(None))
    if city:
        query = query.filter(Visit.city == city)
    return sorted({row[0] for row in query.distinct() if row[0]})


def get_client_visit_history(
    db: Session, city: str, client: str, limit: int = 15
) -> list[dict]:
    """История заметок по точке — комментарии и цели прошлых визитов всех
    амбассадоров к этому (city, client), новые сверху. Пустые (без
    комментария и цели) не показываем."""
    visits = (
        db.query(Visit)
        .filter(Visit.city == city, Visit.client == client)
        .order_by(Visit.created_at.desc())
        .limit(limit * 3)
        .all()
    )

    history = []
    for v in visits:
        comment = (v.comment or "").strip()
        goal = (v.goal or "").strip()
        if not comment and not goal:
            continue
        history.append(
            {
                "date": v.created_at.strftime("%d.%m.%Y"),
                "sale_type": v.sale_type,
                "goal": goal,
                "comment": comment,
                "ambassador": ambassador_display_name(v.ambassador),
            }
        )
        if len(history) >= limit:
            break

    return history


def _validate_visit_payload(
    db: Session,
    *,
    city: str,
    client: str,
    sale_type: str,
    product_ids: list[int],
    sku_classic,
    sku_strong,
    sku_light,
    people_count,
    comment: str,
    goal: str,
) -> dict:
    """Общая проверка анкеты визита для записи (`create_visit`) и
    админ-редактирования (`update_visit`). Возвращает разобранные поля анкеты
    (`sku_*`/`people_count` как int, `comment`/`goal` очищенные), клиент/тип
    точки/ароматы только валидирует. Бросает ValueError с текстом для UI."""
    if client not in sales_options_service.get_clients(db, city=city):
        raise ValueError("Такого клиента нет в списке для этого города")

    if sale_type not in sales_options_service.get_types(db, city=city):
        raise ValueError("Такого типа точки нет в списке для этого города")

    if not product_ids:
        raise ValueError("Выберите хотя бы один аромат")

    valid_ids = {
        row[0]
        for row in db.query(Product.id).filter(
            Product.id.in_(product_ids), Product.is_active.is_(True)
        )
    }
    if set(product_ids) - valid_ids:
        raise ValueError("Часть выбранных ароматов недоступна, обновите страницу")

    comment = (comment or "").strip()
    goal = (goal or "").strip()
    if not comment:
        raise ValueError("Заполните комментарий")
    if not goal:
        raise ValueError("Укажите цель визита")

    return {
        "sku_classic": _parse_count(sku_classic, "SKU на полке — классическая"),
        "sku_strong": _parse_count(sku_strong, "SKU на полке — крепкая"),
        "sku_light": _parse_count(sku_light, "SKU на полке — лёгкая"),
        "people_count": _parse_count(people_count, "Человек на мероприятии"),
        "comment": comment,
        "goal": goal,
    }


def _set_visit_products(db: Session, visit_id: int, product_ids: list[int]) -> None:
    db.query(VisitProduct).filter(VisitProduct.visit_id == visit_id).delete()
    db.flush()
    for product_id in product_ids:
        db.add(VisitProduct(visit_id=visit_id, product_id=product_id))


def create_visit(
    db: Session,
    ambassador: User,
    city: str,
    client: str,
    sale_type: str,
    product_ids: list[int],
    sku_classic=None,
    sku_strong=None,
    sku_light=None,
    people_count=None,
    comment: str = "",
    goal: str = "",
) -> Visit:
    if city != ambassador.city:
        raise ValueError("Вы можете записывать визиты только в своём городе")

    fields = _validate_visit_payload(
        db,
        city=city,
        client=client,
        sale_type=sale_type,
        product_ids=product_ids,
        sku_classic=sku_classic,
        sku_strong=sku_strong,
        sku_light=sku_light,
        people_count=people_count,
        comment=comment,
        goal=goal,
    )

    visit = Visit(
        ambassador_id=ambassador.id,
        city=city,
        client=client,
        sale_type=sale_type,
        **fields,
    )
    db.add(visit)
    db.flush()

    _set_visit_products(db, visit.id, product_ids)

    db.commit()
    db.refresh(visit)
    return visit


def get_visit_product_ids(db: Session, visit_id: int) -> list[int]:
    return [
        row[0]
        for row in db.query(VisitProduct.product_id).filter(
            VisitProduct.visit_id == visit_id
        )
    ]


def update_visit(
    db: Session,
    visit: Visit,
    *,
    client: str,
    sale_type: str,
    product_ids: list[int],
    sku_classic,
    sku_strong,
    sku_light,
    people_count,
    comment: str = "",
    goal: str = "",
    visit_date=None,
) -> Visit:
    """Админ-редактирование визита. Город и амбассадор не меняются — правится
    клиент/тип точки (в пределах города визита), анкета, список ароматов и,
    опционально, дата (`visit_date` — `date`; час/минуты в `created_at`
    сохраняются)."""
    fields = _validate_visit_payload(
        db,
        city=visit.city,
        client=client,
        sale_type=sale_type,
        product_ids=product_ids,
        sku_classic=sku_classic,
        sku_strong=sku_strong,
        sku_light=sku_light,
        people_count=people_count,
        comment=comment,
        goal=goal,
    )

    visit.client = client
    visit.sale_type = sale_type
    for key, value in fields.items():
        setattr(visit, key, value)

    if visit_date is not None:
        visit.created_at = visit.created_at.replace(
            year=visit_date.year, month=visit_date.month, day=visit_date.day
        )

    _set_visit_products(db, visit.id, product_ids)

    db.commit()
    db.refresh(visit)
    return visit


def delete_visit(db: Session, visit: Visit) -> None:
    db.query(VisitProduct).filter(VisitProduct.visit_id == visit.id).delete()
    db.delete(visit)
    db.commit()
