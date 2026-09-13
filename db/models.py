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


class Seller(Base):
    __tablename__ = "sellers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    sales: Mapped[list["Sale"]] = relationship(back_populates="seller")
    transfers_out: Mapped[list["CashTransfer"]] = relationship(
        back_populates="from_seller",
        foreign_keys="CashTransfer.from_seller_id",
    )
    transfers_in: Mapped[list["CashTransfer"]] = relationship(
        back_populates="to_seller",
        foreign_keys="CashTransfer.to_seller_id",
    )
    withdrawals: Mapped[list["CashWithdrawal"]] = relationship(back_populates="seller")


class StickModel(Base):
    __tablename__ = "models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)

    colors: Mapped[list["ColorOption"]] = relationship(
        back_populates="model",
        cascade="all, delete-orphan",
    )
    products: Mapped[list["Product"]] = relationship(back_populates="model")


class ColorOption(Base):
    __tablename__ = "color_options"
    __table_args__ = (UniqueConstraint("model_id", "name", name="uq_color_per_model"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)

    model: Mapped[StickModel] = relationship(back_populates="colors")
    products: Mapped[list["Product"]] = relationship(back_populates="color")


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
            "color_id",
            name="uq_product_sku",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    flex_id: Mapped[int] = mapped_column(ForeignKey("flex_options.id"), nullable=False)
    curve_id: Mapped[int] = mapped_column(ForeignKey("curve_options.id"), nullable=False)
    grip_id: Mapped[int] = mapped_column(ForeignKey("grip_options.id"), nullable=False)
    color_id: Mapped[int] = mapped_column(ForeignKey("color_options.id"), nullable=False)

    model: Mapped[StickModel] = relationship(back_populates="products")
    flex: Mapped[FlexOption] = relationship(back_populates="products")
    curve: Mapped[CurveOption] = relationship(back_populates="products")
    grip: Mapped[GripOption] = relationship(back_populates="products")
    color: Mapped[ColorOption] = relationship(back_populates="products")
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
    seller_id: Mapped[int | None] = mapped_column(ForeignKey("sellers.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    payment_location: Mapped[PaymentLocation] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    batch: Mapped[Batch] = relationship(back_populates="sales")
    seller: Mapped["Seller | None"] = relationship(back_populates="sales")


class CashTransfer(Base):
    __tablename__ = "cash_transfers"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transfer_amount_positive"),
        CheckConstraint(
            "from_seller_id != to_seller_id",
            name="ck_transfer_different_sellers",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id"), nullable=False)
    to_seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    from_seller: Mapped[Seller] = relationship(
        back_populates="transfers_out",
        foreign_keys=[from_seller_id],
    )
    to_seller: Mapped[Seller] = relationship(
        back_populates="transfers_in",
        foreign_keys=[to_seller_id],
    )


class CashWithdrawal(Base):
    __tablename__ = "cash_withdrawals"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_withdrawal_amount_positive"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    seller: Mapped[Seller] = relationship(back_populates="withdrawals")
