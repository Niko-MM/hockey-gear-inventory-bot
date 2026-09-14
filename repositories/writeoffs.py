from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Batch, StockWriteOff
from repositories.sales import OutOfStockError


async def create_writeoff(session: AsyncSession, *, batch_id: int, quantity: int) -> StockWriteOff:
    batch = await session.get(Batch, batch_id)
    if batch is None or quantity < 1 or batch.remaining_quantity < quantity:
        raise OutOfStockError
    batch.remaining_quantity -= quantity
    row = StockWriteOff(batch_id=batch_id, quantity=quantity)
    session.add(row)
    await session.flush()
    return row


async def delete_writeoff(session: AsyncSession, row: StockWriteOff) -> None:
    batch = await session.get(Batch, row.batch_id)
    if batch is None:
        await session.delete(row)
        return
    restored = batch.remaining_quantity + row.quantity
    if restored > batch.quantity_in:
        raise OutOfStockError
    batch.remaining_quantity = restored
    await session.delete(row)
    await session.flush()
