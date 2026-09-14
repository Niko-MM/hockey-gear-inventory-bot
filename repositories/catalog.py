from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Batch, ColorOption, CurveOption, FlexOption, GripOption, Product, StickModel
from db.seed import ensure_default_color


class DuplicateNameError(Exception):
    pass


class InUseError(Exception):
    pass


async def _batches_using(session: AsyncSession, column: ColumnElement[int], item_id: int) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(Batch)
        .join(Product, Product.id == Batch.product_id)
        .where(column == item_id)
    )
    return int(count or 0)


async def _delete_orphan_products(session: AsyncSession, *filters: ColumnElement[bool]) -> None:
    has_batch = select(Batch.id).where(Batch.product_id == Product.id).exists()
    result = await session.execute(select(Product).where(*filters, ~has_batch))
    for product in result.scalars().all():
        await session.delete(product)


async def remove_product_if_unused(session: AsyncSession, product_id: int) -> None:
    remaining = await session.scalar(
        select(func.count()).select_from(Batch).where(Batch.product_id == product_id)
    )
    if remaining:
        return
    product = await session.get(Product, product_id)
    if product is not None:
        await session.delete(product)


async def list_models(session: AsyncSession) -> list[StickModel]:
    result = await session.execute(select(StickModel).order_by(StickModel.name))
    return list(result.scalars().all())


async def get_model(session: AsyncSession, model_id: int) -> StickModel | None:
    return await session.get(StickModel, model_id)


async def create_model(session: AsyncSession, name: str) -> StickModel:
    exists = await session.scalar(select(StickModel.id).where(StickModel.name == name))
    if exists is not None:
        raise DuplicateNameError
    model = StickModel(name=name)
    session.add(model)
    await session.flush()
    await ensure_default_color(session, model)
    return model


async def delete_model(session: AsyncSession, model_id: int) -> None:
    model = await session.get(StickModel, model_id)
    if model is None:
        return
    if await _batches_using(session, Product.model_id, model_id):
        raise InUseError
    await _delete_orphan_products(session, Product.model_id == model_id)
    await session.delete(model)


async def list_colors(session: AsyncSession, model_id: int) -> list[ColorOption]:
    result = await session.execute(
        select(ColorOption)
        .where(ColorOption.model_id == model_id)
        .order_by(ColorOption.is_default.desc(), ColorOption.name)
    )
    return list(result.scalars().all())


async def create_color(session: AsyncSession, model_id: int, name: str) -> ColorOption:
    exists = await session.scalar(
        select(ColorOption.id).where(
            ColorOption.model_id == model_id,
            ColorOption.name == name,
        )
    )
    if exists is not None:
        raise DuplicateNameError
    color = ColorOption(model_id=model_id, name=name, is_default=False)
    session.add(color)
    await session.flush()
    return color


async def delete_color(session: AsyncSession, color_id: int) -> None:
    color = await session.get(ColorOption, color_id)
    if color is None:
        return
    if color.is_default:
        raise InUseError
    if await _batches_using(session, Product.color_id, color_id):
        raise InUseError
    await _delete_orphan_products(session, Product.color_id == color_id)
    await session.delete(color)


async def list_flex(session: AsyncSession) -> list[FlexOption]:
    result = await session.execute(select(FlexOption).order_by(FlexOption.value))
    return list(result.scalars().all())


async def create_flex(session: AsyncSession, value: str) -> FlexOption:
    exists = await session.scalar(select(FlexOption.id).where(FlexOption.value == value))
    if exists is not None:
        raise DuplicateNameError
    item = FlexOption(value=value)
    session.add(item)
    await session.flush()
    return item


async def delete_flex(session: AsyncSession, flex_id: int) -> None:
    item = await session.get(FlexOption, flex_id)
    if item is None:
        return
    if await _batches_using(session, Product.flex_id, flex_id):
        raise InUseError
    await _delete_orphan_products(session, Product.flex_id == flex_id)
    await session.delete(item)


async def list_curves(session: AsyncSession) -> list[CurveOption]:
    result = await session.execute(select(CurveOption).order_by(CurveOption.name))
    return list(result.scalars().all())


async def create_curve(session: AsyncSession, name: str) -> CurveOption:
    exists = await session.scalar(select(CurveOption.id).where(CurveOption.name == name))
    if exists is not None:
        raise DuplicateNameError
    item = CurveOption(name=name)
    session.add(item)
    await session.flush()
    return item


async def delete_curve(session: AsyncSession, curve_id: int) -> None:
    item = await session.get(CurveOption, curve_id)
    if item is None:
        return
    if await _batches_using(session, Product.curve_id, curve_id):
        raise InUseError
    await _delete_orphan_products(session, Product.curve_id == curve_id)
    await session.delete(item)


async def list_grips(session: AsyncSession) -> list[GripOption]:
    result = await session.execute(select(GripOption).order_by(GripOption.name))
    return list(result.scalars().all())


async def create_grip(session: AsyncSession, name: str) -> GripOption:
    exists = await session.scalar(select(GripOption.id).where(GripOption.name == name))
    if exists is not None:
        raise DuplicateNameError
    item = GripOption(name=name)
    session.add(item)
    await session.flush()
    return item


async def delete_grip(session: AsyncSession, grip_id: int) -> None:
    item = await session.get(GripOption, grip_id)
    if item is None:
        return
    if await _batches_using(session, Product.grip_id, grip_id):
        raise InUseError
    await _delete_orphan_products(session, Product.grip_id == grip_id)
    await session.delete(item)


async def find_product(
    session: AsyncSession,
    *,
    model_id: int,
    color_id: int,
    flex_id: int,
    curve_id: int,
    grip_id: int,
) -> Product | None:
    return await session.scalar(
        select(Product).where(
            Product.model_id == model_id,
            Product.color_id == color_id,
            Product.flex_id == flex_id,
            Product.curve_id == curve_id,
            Product.grip_id == grip_id,
        )
    )


async def get_or_create_product(
    session: AsyncSession,
    *,
    model_id: int,
    color_id: int,
    flex_id: int,
    curve_id: int,
    grip_id: int,
) -> Product:
    existing = await session.scalar(
        select(Product).where(
            Product.model_id == model_id,
            Product.color_id == color_id,
            Product.flex_id == flex_id,
            Product.curve_id == curve_id,
            Product.grip_id == grip_id,
        )
    )
    if existing is not None:
        return existing
    product = Product(
        model_id=model_id,
        color_id=color_id,
        flex_id=flex_id,
        curve_id=curve_id,
        grip_id=grip_id,
    )
    session.add(product)
    await session.flush()
    return product
