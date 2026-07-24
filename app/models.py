from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)

    category = Column(String, nullable=False)
    brand = Column(String, nullable=False)
    line = Column(String)
    flavor = Column(String, nullable=False)

    canonical_sku = Column(String, nullable=False)
    canonical_name = Column(String, nullable=False)

    default_weight_g = Column(Integer)

    norm_brand = Column(String, nullable=False)
    norm_flavor = Column(String, nullable=False)

    is_active = Column(Boolean, default=True)
    is_new = Column(Boolean, default=False, nullable=False)


class AbcSegment(Base):
    __tablename__ = "abc_segments"

    id = Column(Integer, primary_key=True, autoincrement=True)

    name = Column(String, unique=True, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)


class ProductAbcRating(Base):
    __tablename__ = "product_abc_ratings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    segment_id = Column(Integer, ForeignKey("abc_segments.id"), nullable=False)
    category = Column(String, nullable=False)

    product = relationship("Product")
    segment = relationship("AbcSegment")

    __table_args__ = (
        UniqueConstraint("product_id", "segment_id", name="uq_product_abc_segment"),
    )


class Sale(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True, autoincrement=True)

    city = Column(String)
    month = Column(String)
    type = Column(String)
    client = Column(String)

    raw_name = Column(String)
    raw_sku = Column(String)

    product_id = Column(Integer, ForeignKey("products.id"))
    sku = Column(String)
    name = Column(String)

    qty = Column(Float)
    weight = Column(Float)

    matched = Column(Boolean, default=False)


class Dashboard(Base):
    __tablename__ = "dashboards"

    id = Column(Integer, primary_key=True, autoincrement=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)

    cities = Column(JSON, nullable=False, default=list)
    clients = Column(JSON, nullable=False, default=list)
    months = Column(JSON, nullable=False, default=list)
    compare_mode = Column(String, nullable=False, default="aggregate")

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    widgets = relationship(
        "DashboardWidget", cascade="all, delete-orphan", order_by="DashboardWidget.id"
    )


class DashboardWidget(Base):
    __tablename__ = "dashboard_widgets"

    id = Column(Integer, primary_key=True, autoincrement=True)

    dashboard_id = Column(Integer, ForeignKey("dashboards.id"), nullable=False)
    metric = Column(String, nullable=False)
    widget_type = Column(String, nullable=False)
    chart_kind = Column(String, nullable=True)

    grid_x = Column(Integer, nullable=False, default=0)
    grid_y = Column(Integer, nullable=False, default=0)
    grid_w = Column(Integer, nullable=False, default=3)
    grid_h = Column(Integer, nullable=False, default=2)
