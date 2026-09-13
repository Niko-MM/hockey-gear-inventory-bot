from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Batch, CashWithdrawal, City, Sale, Seller


@dataclass(frozen=True)
class PeriodReport:
    start: date
    end: date
    cities: list[tuple[str, int]]
    total_qty: int
    revenue: Decimal
    profit: Decimal
    sales_by_seller: list[tuple[str, Decimal]]
    withdrawals_by_seller: list[tuple[str, Decimal]]


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
    profit = revenue_dec - Decimal(cost)

    seller_rows = await session.execute(
        select(Seller.name, func.coalesce(func.sum(Sale.total_amount), 0))
        .join(Sale, Sale.seller_id == Seller.id)
        .where(from_day, to_day)
        .group_by(Seller.name)
        .order_by(Seller.name)
    )
    sales_by_seller = [(name, Decimal(amount)) for name, amount in seller_rows.all()]

    wd_from, wd_to = _in_period(CashWithdrawal.created_at, start, end)
    taken_rows = await session.execute(
        select(Seller.name, func.coalesce(func.sum(CashWithdrawal.amount), 0))
        .join(CashWithdrawal, CashWithdrawal.seller_id == Seller.id)
        .where(wd_from, wd_to)
        .group_by(Seller.name)
        .order_by(Seller.name)
    )
    withdrawals_by_seller = [(name, Decimal(amount)) for name, amount in taken_rows.all()]

    return PeriodReport(
        start=start,
        end=end,
        cities=cities,
        total_qty=total_qty,
        revenue=revenue_dec,
        profit=profit,
        sales_by_seller=sales_by_seller,
        withdrawals_by_seller=withdrawals_by_seller,
    )
