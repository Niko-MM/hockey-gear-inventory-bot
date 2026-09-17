from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Batch,
    CashDeposit,
    CashTransfer,
    CashWithdrawal,
    City,
    Product,
    Sale,
    Seller,
    StickModel,
    StockWriteOff,
)
from utils.dates import period_utc_bounds


@dataclass(frozen=True)
class CitySales:
    name: str
    revenue: Decimal
    cost: Decimal
    profit: Decimal
    models: list[tuple[str, int]]


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
    sales_by_model: list[tuple[str, int]]
    sales_by_seller: list[tuple[str, Decimal, int]]
    incoming_by_city: list[tuple[str, int, Decimal]]
    transfers: list[tuple[str, str, Decimal]]
    withdrawals_by_seller: list[tuple[str, Decimal]]
    writeoffs_by_city: list[tuple[str, int, Decimal]]
    wholesale_by_seller: list[tuple[str, Decimal]]
    wholesale_total: Decimal
    sales_by_city: list[CitySales]


def _in_period(column, start: date, end: date):
    begin, finish = period_utc_bounds(start, end)
    return column >= begin, column < finish


async def period_report(session: AsyncSession, start: date, end: date) -> PeriodReport:
    from_day, to_day = _in_period(Sale.created_at, start, end)
    city_rows = await session.execute(
        select(
            City.name,
            func.coalesce(func.sum(Sale.quantity), 0),
            func.coalesce(func.sum(Sale.total_amount), 0),
            func.coalesce(func.sum(Batch.purchase_price * Sale.quantity), 0),
        )
        .join(Batch, Sale.batch_id == Batch.id)
        .join(City, Batch.city_id == City.id)
        .where(from_day, to_day)
        .group_by(City.name)
        .order_by(City.name)
    )
    city_stats = city_rows.all()
    cities = [(name, int(qty)) for name, qty, _, _ in city_stats]
    total_qty = sum(qty for _, qty in cities)

    qty_by_model = func.coalesce(func.sum(Sale.quantity), 0)
    model_rows = await session.execute(
        select(StickModel.name, qty_by_model)
        .select_from(Sale)
        .join(Batch, Sale.batch_id == Batch.id)
        .join(Product, Batch.product_id == Product.id)
        .join(StickModel, Product.model_id == StickModel.id)
        .where(from_day, to_day)
        .group_by(StickModel.name)
        .order_by(qty_by_model.desc(), StickModel.name)
    )
    sales_by_model = [(name, int(qty)) for name, qty in model_rows.all()]

    model_city_rows = await session.execute(
        select(City.name, StickModel.name, qty_by_model)
        .select_from(Sale)
        .join(Batch, Sale.batch_id == Batch.id)
        .join(City, Batch.city_id == City.id)
        .join(Product, Batch.product_id == Product.id)
        .join(StickModel, Product.model_id == StickModel.id)
        .where(from_day, to_day)
        .group_by(City.name, StickModel.name)
        .order_by(City.name, qty_by_model.desc(), StickModel.name)
    )
    models_by_city: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for city_name, model_name, qty in model_city_rows.all():
        models_by_city[city_name].append((model_name, int(qty)))
    sales_by_city = [
        CitySales(
            name=name,
            revenue=Decimal(revenue),
            cost=Decimal(cost),
            profit=Decimal(revenue) - Decimal(cost),
            models=models_by_city.get(name, []),
        )
        for name, _, revenue, cost in city_stats
    ]

    receipts = int(
        await session.scalar(select(func.count()).select_from(Sale).where(from_day, to_day)) or 0
    )
    revenue_dec = sum((row.revenue for row in sales_by_city), Decimal("0"))
    cost_dec = sum((row.cost for row in sales_by_city), Decimal("0"))
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

    dep_from, dep_to = _in_period(CashDeposit.created_at, start, end)
    deposit_rows = await session.execute(
        select(Seller.name, func.coalesce(func.sum(CashDeposit.amount), 0))
        .join(CashDeposit, CashDeposit.seller_id == Seller.id)
        .where(dep_from, dep_to)
        .group_by(Seller.name)
        .order_by(Seller.name)
    )
    wholesale_by_seller = [(name, Decimal(amount)) for name, amount in deposit_rows.all()]
    wholesale_total = sum((amount for _, amount in wholesale_by_seller), Decimal("0"))

    return PeriodReport(
        start=start,
        end=end,
        cities=cities,
        total_qty=total_qty,
        receipts=receipts,
        revenue=revenue_dec,
        cost=cost_dec,
        profit=profit,
        sales_by_model=sales_by_model,
        sales_by_seller=sales_by_seller,
        incoming_by_city=incoming_by_city,
        transfers=transfers,
        withdrawals_by_seller=withdrawals_by_seller,
        writeoffs_by_city=writeoffs_by_city,
        wholesale_by_seller=wholesale_by_seller,
        wholesale_total=wholesale_total,
        sales_by_city=sales_by_city,
    )
