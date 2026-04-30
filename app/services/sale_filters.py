from ..models import Sale


def build_sale_filters(
    city: str | None = None,
    months: list[str] | None = None,
    sale_types: list[str] | None = None,
    client: str | None = None,
    sale_type: str | None = None,
    matched: str | None = None,
):
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

    return filters
