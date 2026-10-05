from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import Batch, PaymentLocation, Product, Reservation, Sale, Seller
from repositories.sales import OutOfStockError


def _hold_load():
    return (
        selectinload(Reservation.seller),
        selectinload(Reservation.batch).options(
            selectinload(Batch.city),
            selectinload(Batch.product).options(
                selectinload(Product.model),
                selectinload(Product.color),
                selectinload(Product.flex),
                selectinload(Product.grip),
                selectinload(Product.curve),
            ),
        ),
    )


async def reserved_quantity(session: AsyncSession) -> int:
    total = await session.scalar(select(func.coalesce(func.sum(Reservation.quantity), 0)))
    return int(total or 0)


async def list_holds(session: AsyncSession) -> list[Reservation]:
    result = await session.execute(
        select(Reservation).options(*_hold_load()).order_by(Reservation.created_at.desc())
    )
    return list(result.scalars().all())


async def get_hold(session: AsyncSession, hold_id: int) -> Reservation | None:
    return await session.get(Reservation, hold_id, options=list(_hold_load()))


async def create_reservation(
    session: AsyncSession,
    *,
    batch_id: int,
    seller_id: int,
    total_amount: Decimal,
    quantity: int = 1,
) -> Reservation:
    batch = await session.get(Batch, batch_id)
    seller = await session.get(Seller, seller_id)
    if batch is None or seller is None or quantity < 1 or batch.remaining_quantity < quantity:
        raise OutOfStockError
    batch.remaining_quantity -= quantity
    hold = Reservation(
        batch_id=batch_id,
        seller_id=seller_id,
        quantity=quantity,
        total_amount=total_amount,
    )
    session.add(hold)
    await session.flush()
    return hold


async def cancel_reservation(session: AsyncSession, hold: Reservation) -> None:
    batch = await session.get(Batch, hold.batch_id)
    if batch is None:
        await session.delete(hold)
        await session.flush()
        return
    restored = batch.remaining_quantity + hold.quantity
    if restored > batch.quantity_in:
        raise OutOfStockError
    batch.remaining_quantity = restored
    await session.delete(hold)
    await session.flush()


async def complete_reservation(session: AsyncSession, hold: Reservation) -> Sale:
    sale = Sale(
        batch_id=hold.batch_id,
        seller_id=hold.seller_id,
        quantity=hold.quantity,
        total_amount=hold.total_amount,
        payment_location=PaymentLocation.WITH_ADMIN,
    )
    session.add(sale)
    await session.delete(hold)
    await session.flush()
    return sale
