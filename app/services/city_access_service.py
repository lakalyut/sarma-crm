"""Request-session city restrictions, shared by analytics and Telegram."""

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from ..auth_models import User
from ..models import CityRegion, EventLog, Region, Sale, Visit


def apply_city_scope(db: Session, user: User) -> None:
    if user.role == "brand_ambassador":
        db.info["brand_cities"] = tuple(user.allowed_cities)
    else:
        db.info.pop("brand_cities", None)


@event.listens_for(Session, "do_orm_execute")
def restrict_city_queries(state):
    cities = state.session.info.get("brand_cities")
    if (
        cities is None
        or not state.is_select
        or state.execution_options.get("global_leaderboard")
    ):
        return
    # Apply before SQL execution, including aggregates, joins, aliases and exports.
    for model in (Sale, Visit, EventLog, CityRegion):
        state.statement = state.statement.options(
            with_loader_criteria(model, model.city.in_(cities), include_aliases=True)
        )
    state.statement = state.statement.options(
        with_loader_criteria(
            Region,
            Region.id.in_(
                state.session.query(CityRegion.region_id)
                .filter(CityRegion.city.in_(cities))
                .statement
            ),
            include_aliases=True,
        )
    )
