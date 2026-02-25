from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String

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
