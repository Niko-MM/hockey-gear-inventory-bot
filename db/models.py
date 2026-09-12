from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class PaymentLocation(str, Enum):
    WITH_ADMIN = "with_admin"
    IN_CITY = "in_city"


class City(Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    batches: Mapped[list["Batch"]] = relationship(back_populates="city")


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    models: Mapped[list["StickModel"]] = relationship(back_populates="brand")


class StickModel(Base):
    __tablename__ = "models"
    __table_args__ = (UniqueConstraint("brand_id", "name", name="uq_model_per_brand"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)

    brand: Mapped[Brand] = relationship(back_populates="models")
    products: Mapped[list["Product"]] = relationship(back_populates="model")


class FlexOption(Base):
    __tablename__ = "flex_options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    products: Mapped[list["Product"]] = relationship(back_populates="flex")


class CurveOption(Base):
    __tablename__ = "curve_options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    products: Mapped[list["Product"]] = relationship(back_populates="curve")


class GripOption(Base):
    __tablename__ = "grip_options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    products: Mapped[list["Product"]] = relationship(back_populates="grip")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint(
            "model_id",
            "flex_id",
            "curve_id",
            "grip_id",
            name="uq_product_sku",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    flex_id: Mapped[int] = mapped_column(ForeignKey("flex_options.id"), nullable=False)
    curve_id: Mapped[int] = mapped_column(ForeignKey("curve_options.id"), nullable=False)
    grip_id: Mapped[int] = mapped_column(ForeignKey("grip_options.id"), nullable=False)

    model: Mapped[StickModel] = relationship(back_populates="products")
    flex: Mapped[FlexOption] = relationship(back_populates="products")
    curve: Mapped[CurveOption] = relationship(back_populates="products")
    grip: Mapped[GripOption] = relationship(back_populates="products")
    batches: Mapped[list["Batch"]] = relationship(back_populates="product")


class Batch(Base):
    __tablename__ = "batches"
    __table_args__ = (
        CheckConstraint("quantity_in > 0", name="ck_batch_quantity_in_positive"),
        CheckConstraint("remaining_quantity >= 0", name="ck_batch_remaining_non_negative"),
        CheckConstraint(
            "remaining_quantity <= quantity_in",
            name="ck_batch_remaining_not_above_in",
        ),
        CheckConstraint("purchase_price >= 0", name="ck_batch_purchase_price_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), nullable=False)
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    quantity_in: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    product: Mapped[Product] = relationship(back_populates="batches")
    city: Mapped[City] = relationship(back_populates="batches")
    sales: Mapped[list["Sale"]] = relationship(back_populates="batch")


class Sale(Base):
    __tablename__ = "sales"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_sale_quantity_positive"),
        CheckConstraint("total_amount >= 0", name="ck_sale_total_amount_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    payment_location: Mapped[PaymentLocation] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    batch: Mapped[Batch] = relationship(back_populates="sales")
