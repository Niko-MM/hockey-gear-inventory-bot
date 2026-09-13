from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import CashTransfer, CashWithdrawal, Sale, Seller
from repositories.catalog import DuplicateNameError, InUseError


class InsufficientFundsError(Exception):
    pass


async def list_sellers(session: AsyncSession) -> list[Seller]:
    result = await session.execute(select(Seller).order_by(Seller.name))
    return list(result.scalars().all())


async def get_seller(session: AsyncSession, seller_id: int) -> Seller | None:
    return await session.get(Seller, seller_id)


async def create_seller(session: AsyncSession, name: str) -> Seller:
    exists = await session.scalar(select(Seller.id).where(Seller.name == name))
    if exists is not None:
        raise DuplicateNameError
    seller = Seller(name=name)
    session.add(seller)
    await session.flush()
    return seller


async def delete_seller(session: AsyncSession, seller_id: int) -> None:
    seller = await session.get(Seller, seller_id)
    if seller is None:
        return
    sales_count = await session.scalar(
        select(func.count()).select_from(Sale).where(Sale.seller_id == seller_id)
    )
    transfers_count = await session.scalar(
        select(func.count())
        .select_from(CashTransfer)
        .where(
            or_(
                CashTransfer.from_seller_id == seller_id,
                CashTransfer.to_seller_id == seller_id,
            )
        )
    )
    withdrawals_count = await session.scalar(
        select(func.count())
        .select_from(CashWithdrawal)
        .where(CashWithdrawal.seller_id == seller_id)
    )
    if sales_count or transfers_count or withdrawals_count:
        raise InUseError
    await session.delete(seller)


async def seller_balance(session: AsyncSession, seller_id: int) -> Decimal:
    sales_total = await session.scalar(
        select(func.coalesce(func.sum(Sale.total_amount), 0)).where(Sale.seller_id == seller_id)
    )
    incoming = await session.scalar(
        select(func.coalesce(func.sum(CashTransfer.amount), 0)).where(
            CashTransfer.to_seller_id == seller_id
        )
    )
    outgoing = await session.scalar(
        select(func.coalesce(func.sum(CashTransfer.amount), 0)).where(
            CashTransfer.from_seller_id == seller_id
        )
    )
    taken = await session.scalar(
        select(func.coalesce(func.sum(CashWithdrawal.amount), 0)).where(
            CashWithdrawal.seller_id == seller_id
        )
    )
    return Decimal(sales_total) + Decimal(incoming) - Decimal(outgoing) - Decimal(taken)


async def list_balances(session: AsyncSession) -> list[tuple[Seller, Decimal]]:
    sellers = await list_sellers(session)
    rows: list[tuple[Seller, Decimal]] = []
    for seller in sellers:
        rows.append((seller, await seller_balance(session, seller.id)))
    return rows


async def transfer(
    session: AsyncSession,
    from_seller_id: int,
    to_seller_id: int,
    amount: Decimal,
) -> CashTransfer:
    if from_seller_id == to_seller_id:
        raise InUseError
    if amount <= 0:
        raise InsufficientFundsError
    balance = await seller_balance(session, from_seller_id)
    if amount > balance:
        raise InsufficientFundsError
    record = CashTransfer(
        from_seller_id=from_seller_id,
        to_seller_id=to_seller_id,
        amount=amount,
    )
    session.add(record)
    await session.flush()
    return record


async def withdraw(
    session: AsyncSession,
    seller_id: int,
    amount: Decimal,
) -> CashWithdrawal:
    if amount <= 0:
        raise InsufficientFundsError
    balance = await seller_balance(session, seller_id)
    if amount > balance:
        raise InsufficientFundsError
    record = CashWithdrawal(seller_id=seller_id, amount=amount)
    session.add(record)
    await session.flush()
    return record
