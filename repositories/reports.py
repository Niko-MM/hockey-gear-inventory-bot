from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Batch, CashTransfer, CashWithdrawal, City, Sale, Seller, StockWriteOff


@dataclass(frozen=True)
class PeriodReport:
    start: date
    end: date
    cities: list[tuple[str, int]]
    total_qty: int
    receipts: int
    revenue: Decimal
    cost: Decimal
    profit: Decimal
    sales_by_seller: list[tuple[str, Decimal, int]]
    incoming_by_city: list[tuple[str, int, Decimal]]
    transfers: list[tuple[str, str, Decimal]]
    withdrawals_by_seller: list[tuple[str, Decimal]]
    writeoffs_by_city: list[tuple[str, int, Decimal]]


def _in_period(column, start: date, end: date):
    day = func.date(column)
    return day >= start.isoformat(), day <= end.isoformat()


async def period_report(session: AsyncSession, start: date, end: date) -> PeriodReport:
    from_day, to_day = _in_period(Sale.created_at, start, end)
    city_rows = await session.execute(
        select(City.name, func.coalesce(func.sum(Sale.quantity), 0))
        .join(Batch, Sale.batch_id == Batch.id)
        .join(City, Batch.city_id == City.id)
        .where(from_day, to_day)
        .group_by(City.name)
        .order_by(City.name)
    )
    cities = [(name, int(qty)) for name, qty in city_rows.all()]
    total_qty = sum(qty for _, qty in cities)

    receipts = int(
        await session.scalar(select(func.count()).select_from(Sale).where(from_day, to_day)) or 0
    )
    revenue = await session.scalar(
        select(func.coalesce(func.sum(Sale.total_amount), 0)).where(from_day, to_day)
    )
    cost = await session.scalar(
        select(func.coalesce(func.sum(Batch.purchase_price * Sale.quantity), 0))
        .select_from(Sale)
        .join(Batch, Sale.batch_id == Batch.id)
        .where(from_day, to_day)
    )
    revenue_dec = Decimal(revenue)
    cost_dec = Decimal(cost)
    profit = revenue_dec - cost_dec

    seller_rows = await session.execute(
        select(
            Seller.name,
            func.coalesce(func.sum(Sale.total_amount), 0),
            func.coalesce(func.sum(Sale.quantity), 0),
        )
        .join(Sale, Sale.seller_id == Seller.id)
        .where(from_day, to_day)
        .group_by(Seller.name)
        .order_by(Seller.name)
    )
    sales_by_seller = [
        (name, Decimal(amount), int(qty)) for name, amount, qty in seller_rows.all()
    ]

    in_from, in_to = _in_period(Batch.created_at, start, end)
    incoming_rows = await session.execute(
        select(
            City.name,
            func.coalesce(func.sum(Batch.quantity_in), 0),
            func.coalesce(func.sum(Batch.purchase_price * Batch.quantity_in), 0),
        )
        .select_from(Batch)
        .join(City, Batch.city_id == City.id)
        .where(in_from, in_to)
        .group_by(City.name)
        .order_by(City.name)
    )
    incoming_by_city = [
        (name, int(qty), Decimal(amount)) for name, qty, amount in incoming_rows.all()
    ]

    tr_from, tr_to = _in_period(CashTransfer.created_at, start, end)
    from_seller = aliased(Seller)
    to_seller = aliased(Seller)
    transfer_rows = await session.execute(
        select(from_seller.name, to_seller.name, CashTransfer.amount)
        .select_from(CashTransfer)
        .join(from_seller, from_seller.id == CashTransfer.from_seller_id)
        .join(to_seller, to_seller.id == CashTransfer.to_seller_id)
        .where(tr_from, tr_to)
        .order_by(CashTransfer.created_at, CashTransfer.id)
    )
    transfers = [
        (source, target, Decimal(amount)) for source, target, amount in transfer_rows.all()
    ]

    wd_from, wd_to = _in_period(CashWithdrawal.created_at, start, end)
    taken_rows = await session.execute(
        select(Seller.name, func.coalesce(func.sum(CashWithdrawal.amount), 0))
        .join(CashWithdrawal, CashWithdrawal.seller_id == Seller.id)
        .where(wd_from, wd_to)
        .group_by(Seller.name)
        .order_by(Seller.name)
    )
    withdrawals_by_seller = [(name, Decimal(amount)) for name, amount in taken_rows.all()]

    wo_from, wo_to = _in_period(StockWriteOff.created_at, start, end)
    writeoff_rows = await session.execute(
        select(
            City.name,
            func.coalesce(func.sum(StockWriteOff.quantity), 0),
            func.coalesce(func.sum(Batch.purchase_price * StockWriteOff.quantity), 0),
        )
        .select_from(StockWriteOff)
        .join(Batch, StockWriteOff.batch_id == Batch.id)
        .join(City, Batch.city_id == City.id)
        .where(wo_from, wo_to)
        .group_by(City.name)
        .order_by(City.name)
    )
    writeoffs_by_city = [
        (name, int(qty), Decimal(amount)) for name, qty, amount in writeoff_rows.all()
    ]

    return PeriodReport(
        start=start,
        end=end,
        cities=cities,
        total_qty=total_qty,
        receipts=receipts,
        revenue=revenue_dec,
        cost=cost_dec,
        profit=profit,
        sales_by_seller=sales_by_seller,
        incoming_by_city=incoming_by_city,
        transfers=transfers,
        withdrawals_by_seller=withdrawals_by_seller,
        writeoffs_by_city=writeoffs_by_city,
    )
