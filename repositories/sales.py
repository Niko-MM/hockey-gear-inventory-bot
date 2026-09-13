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
    quantity: int = 1,
) -> Sale:
    batch = await session.get(Batch, batch_id)
    if batch is None or quantity < 1 or batch.remaining_quantity < quantity:
        raise OutOfStockError
    batch.remaining_quantity -= quantity
    sale = Sale(
        batch_id=batch_id,
        seller_id=seller_id,
        quantity=quantity,
        total_amount=total_amount,
        payment_location=PaymentLocation.WITH_ADMIN,
    )
    session.add(sale)
    await session.flush()
    return sale


async def delete_sale(session: AsyncSession, sale: Sale) -> None:
    batch = await session.get(Batch, sale.batch_id)
    if batch is None:
        await session.delete(sale)
        return
    restored = batch.remaining_quantity + sale.quantity
    if restored > batch.quantity_in:
        raise OutOfStockError
    batch.remaining_quantity = restored
    await session.delete(sale)
