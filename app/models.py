from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
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


class Region(Base):
    __tablename__ = "regions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    name = Column(String, unique=True, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)


class CityRegion(Base):
    __tablename__ = "city_regions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    city = Column(String, unique=True, nullable=False)
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=False)

    region = relationship("Region")


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

    __table_args__ = (
        # Почти вся аналитика фильтрует по городу (build_sale_filters, всегда
        # первым) и часто сразу сужает по месяцам — префикс (city) покрывает
        # и просто "WHERE city = ...", составной индекс закрывает обе формы
        # одним индексом вместо двух.
        Index("ix_sales_city_month", "city", "month"),
        # Детализация клиента (get_client_detail_data) и «Свод»/«Анализ по
        # клиентам» фильтруют по этой тройке точным совпадением (без
        # диапазонов) — отдельный индекс, т.к. порядок колонок другой и
        # (city, month) для него бесполезен.
        Index("ix_sales_city_client_type", "city", "client", "type"),
    )


class EventLog(Base):
    __tablename__ = "event_log"

    id = Column(Integer, primary_key=True, autoincrement=True)

    event_type = Column(String, nullable=False, default="import")
    city = Column(String, nullable=False)
    months = Column(String, nullable=False, default="")

    rows_imported = Column(Integer, nullable=False, default=0)
    rows_unmatched = Column(Integer, nullable=False, default=0)

    user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    user = relationship("User")
