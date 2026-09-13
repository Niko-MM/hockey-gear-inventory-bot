from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Batch, City


async def list_cities(session: AsyncSession) -> list[City]:
    result = await session.execute(select(City).order_by(City.name))
    return list(result.scalars().all())


async def create_batch(
    session: AsyncSession,
    *,
    product_id: int,
    city_id: int,
    quantity: int,
    purchase_price: Decimal,
) -> Batch:
    batch = Batch(
        product_id=product_id,
        city_id=city_id,
        purchase_price=purchase_price,
        quantity_in=quantity,
        remaining_quantity=quantity,
    )
    session.add(batch)
    await session.flush()
    return batch
