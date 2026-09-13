from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Batch, PaymentLocation, Sale


class OutOfStockError(Exception):
    pass


async def create_sale(
    session: AsyncSession,
    *,
    batch_id: int,
    seller_id: int,
    total_amount: Decimal,
) -> Sale:
    batch = await session.get(Batch, batch_id)
    if batch is None or batch.remaining_quantity < 1:
        raise OutOfStockError
    batch.remaining_quantity -= 1
    sale = Sale(
        batch_id=batch_id,
        seller_id=seller_id,
        quantity=1,
        total_amount=total_amount,
        payment_location=PaymentLocation.WITH_ADMIN,
    )
    session.add(sale)
    await session.flush()
    return sale
