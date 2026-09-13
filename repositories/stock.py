from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Batch, City, ColorOption, CurveOption, FlexOption, GripOption, Product, StickModel


async def cities_with_stock(session: AsyncSession) -> list[tuple[City, int]]:
    qty = func.sum(Batch.remaining_quantity)
    result = await session.execute(
        select(City, qty)
        .join(Batch, Batch.city_id == City.id)
        .where(Batch.remaining_quantity > 0)
        .group_by(City.id, City.name)
        .order_by(City.name)
    )
    return [(city, int(count)) for city, count in result.all()]


async def model_colors_with_stock(
    session: AsyncSession,
    city_id: int,
) -> list[tuple[StickModel, ColorOption, int]]:
    qty = func.sum(Batch.remaining_quantity)
    result = await session.execute(
        select(StickModel, ColorOption, qty)
        .join(Product, Product.model_id == StickModel.id)
        .join(ColorOption, ColorOption.id == Product.color_id)
        .join(Batch, Batch.product_id == Product.id)
        .where(Batch.city_id == city_id, Batch.remaining_quantity > 0)
        .group_by(
            StickModel.id,
            StickModel.name,
            ColorOption.id,
            ColorOption.model_id,
            ColorOption.name,
            ColorOption.is_default,
        )
        .order_by(StickModel.name, ColorOption.is_default.desc(), ColorOption.name)
    )
    return [(model, color, int(count)) for model, color, count in result.all()]


async def flex_with_stock(
    session: AsyncSession,
    *,
    city_id: int,
    model_id: int,
    color_id: int,
) -> list[tuple[FlexOption, int]]:
    qty = func.sum(Batch.remaining_quantity)
    result = await session.execute(
        select(FlexOption, qty)
        .join(Product, Product.flex_id == FlexOption.id)
        .join(Batch, Batch.product_id == Product.id)
        .where(
            Batch.city_id == city_id,
            Batch.remaining_quantity > 0,
            Product.model_id == model_id,
            Product.color_id == color_id,
        )
        .group_by(FlexOption.id, FlexOption.value)
        .order_by(FlexOption.value)
    )
    return [(item, int(count)) for item, count in result.all()]


async def grips_with_stock(
    session: AsyncSession,
    *,
    city_id: int,
    model_id: int,
    color_id: int,
    flex_id: int,
) -> list[tuple[GripOption, int]]:
    qty = func.sum(Batch.remaining_quantity)
    result = await session.execute(
        select(GripOption, qty)
        .join(Product, Product.grip_id == GripOption.id)
        .join(Batch, Batch.product_id == Product.id)
        .where(
            Batch.city_id == city_id,
            Batch.remaining_quantity > 0,
            Product.model_id == model_id,
            Product.color_id == color_id,
            Product.flex_id == flex_id,
        )
        .group_by(GripOption.id, GripOption.name)
        .order_by(GripOption.name)
    )
    return [(item, int(count)) for item, count in result.all()]


async def curves_with_stock(
    session: AsyncSession,
    *,
    city_id: int,
    model_id: int,
    color_id: int,
    flex_id: int,
    grip_id: int,
) -> list[tuple[CurveOption, int]]:
    qty = func.sum(Batch.remaining_quantity)
    result = await session.execute(
        select(CurveOption, qty)
        .join(Product, Product.curve_id == CurveOption.id)
        .join(Batch, Batch.product_id == Product.id)
        .where(
            Batch.city_id == city_id,
            Batch.remaining_quantity > 0,
            Product.model_id == model_id,
            Product.color_id == color_id,
            Product.flex_id == flex_id,
            Product.grip_id == grip_id,
        )
        .group_by(CurveOption.id, CurveOption.name)
        .order_by(CurveOption.name)
    )
    return [(item, int(count)) for item, count in result.all()]


async def batches_in_stock(
    session: AsyncSession,
    *,
    city_id: int,
    product_id: int,
) -> list[Batch]:
    result = await session.execute(
        select(Batch)
        .where(
            Batch.city_id == city_id,
            Batch.product_id == product_id,
            Batch.remaining_quantity > 0,
        )
        .order_by(Batch.purchase_price, Batch.id)
    )
    return list(result.scalars().all())
