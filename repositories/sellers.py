from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import CashDeposit, CashTransfer, CashWithdrawal, Reservation, Sale, Seller
from repositories.catalog import DuplicateNameError, InUseError


class InsufficientFundsError(Exception):
    pass


class InactiveSellerError(Exception):
    pass


class SellerBalanceError(Exception):
    pass


class SellerHasHoldError(Exception):
    pass


async def list_sellers(session: AsyncSession) -> list[Seller]:
    result = await session.execute(
        select(Seller).where(Seller.active.is_(True)).order_by(Seller.name)
    )
    return list(result.scalars().all())


async def get_seller(session: AsyncSession, seller_id: int) -> Seller | None:
    return await session.get(Seller, seller_id)


async def require_active(session: AsyncSession, *seller_ids: int) -> None:
    for seller_id in seller_ids:
        seller = await session.get(Seller, seller_id)
        if seller is None or not seller.active:
            raise InactiveSellerError


async def create_seller(session: AsyncSession, name: str) -> Seller:
    seller = await session.scalar(select(Seller).where(Seller.name == name))
    if seller is None:
        seller = Seller(name=name, active=True)
        session.add(seller)
        await session.flush()
        return seller
    if seller.active:
        raise DuplicateNameError
    seller.active = True
    await session.flush()
    return seller


async def delete_seller(session: AsyncSession, seller_id: int) -> None:
    seller = await session.get(Seller, seller_id)
    if seller is None or not seller.active:
        return
    balance = await seller_balance(session, seller_id)
    if balance != 0:
        raise SellerBalanceError
    holds_count = await session.scalar(
        select(func.count()).select_from(Reservation).where(Reservation.seller_id == seller_id)
    )
    if holds_count:
        raise SellerHasHoldError
    seller.active = False
    await session.flush()


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
    deposited = await session.scalar(
        select(func.coalesce(func.sum(CashDeposit.amount), 0)).where(
            CashDeposit.seller_id == seller_id
        )
    )
    return (
        Decimal(sales_total)
        + Decimal(incoming)
        + Decimal(deposited)
        - Decimal(outgoing)
        - Decimal(taken)
    )


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
    await require_active(session, from_seller_id, to_seller_id)
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
    await require_active(session, seller_id)
    if amount <= 0:
        raise InsufficientFundsError
    balance = await seller_balance(session, seller_id)
    if amount > balance:
        raise InsufficientFundsError
    record = CashWithdrawal(seller_id=seller_id, amount=amount)
    session.add(record)
    await session.flush()
    return record


async def deposit(
    session: AsyncSession,
    seller_id: int,
    amount: Decimal,
) -> CashDeposit:
    await require_active(session, seller_id)
    if amount <= 0:
        raise InsufficientFundsError
    record = CashDeposit(seller_id=seller_id, amount=amount)
    session.add(record)
    await session.flush()
    return record


async def delete_deposit(session: AsyncSession, row: CashDeposit) -> None:
    balance = await seller_balance(session, row.seller_id)
    if Decimal(row.amount) > balance:
        raise InsufficientFundsError
    await session.delete(row)
