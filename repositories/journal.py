from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import Batch, CashTransfer, CashWithdrawal, Product, Sale, StockWriteOff
from repositories import catalog
from repositories.sales import OutOfStockError, delete_sale
from repositories.writeoffs import delete_writeoff
from utils.money import format_money

JOURNAL_LIMIT = 20


class CannotUndoError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class JournalEntry:
    kind: str
    item_id: int
    created_at: datetime
    button: str
    title: str
    body: str
    can_undo: bool
    block_reason: str = ""


def _when(moment: datetime) -> str:
    return moment.strftime("%d.%m %H:%M")


def _color_title(color) -> str:
    if color.is_default:
        return f"{color.name} (классика)"
    return color.name


def _sku(product: Product) -> str:
    return (
        f"{product.model.name} / {_color_title(product.color)} · "
        f"{product.flex.value} · {product.grip.name} · {product.curve.name}"
    )


def _product_load():
    return selectinload(Batch.product).options(
        selectinload(Product.model),
        selectinload(Product.color),
        selectinload(Product.flex),
        selectinload(Product.grip),
        selectinload(Product.curve),
    )


def _from_sale(sale: Sale) -> JournalEntry:
    batch = sale.batch
    city = batch.city.name
    sku = _sku(batch.product)
    seller = sale.seller.name if sale.seller else "—"
    qty = f"{sale.quantity} шт"
    money = format_money(sale.total_amount)
    return JournalEntry(
        kind="sale",
        item_id=sale.id,
        created_at=sale.created_at,
        button=f"Продажа · {_when(sale.created_at)} · {qty} · {money}",
        title="Продажа",
        body=(
            f"{_when(sale.created_at)}\n"
            f"{city}\n"
            f"{sku}\n"
            f"{qty} · чек {money}\n"
            f"Касса: {seller}"
        ),
        can_undo=True,
    )


def _from_batch(batch: Batch) -> JournalEntry:
    has_sales = bool(batch.sales)
    leftover_changed = batch.quantity_in != batch.remaining_quantity
    sku = _sku(batch.product)
    if has_sales:
        block_reason = "С этой партии уже продавали."
    elif leftover_changed:
        block_reason = "С этой партии уже списывали."
    else:
        block_reason = ""
    return JournalEntry(
        kind="income",
        item_id=batch.id,
        created_at=batch.created_at,
        button=(
            f"Поступление · {_when(batch.created_at)} · "
            f"{batch.city.name} · {batch.quantity_in} шт"
        ),
        title="Поступление",
        body=(
            f"{_when(batch.created_at)}\n"
            f"{batch.city.name}\n"
            f"{sku}\n"
            f"Пришло {batch.quantity_in} шт · осталось {batch.remaining_quantity}\n"
            f"Закуп: {format_money(batch.purchase_price)}"
        ),
        can_undo=not has_sales and not leftover_changed,
        block_reason=block_reason,
    )


def _from_transfer(row: CashTransfer) -> JournalEntry:
    money = format_money(row.amount)
    return JournalEntry(
        kind="transfer",
        item_id=row.id,
        created_at=row.created_at,
        button=(
            f"Перевод · {_when(row.created_at)} · "
            f"{row.from_seller.name} → {row.to_seller.name} · {money}"
        ),
        title="Перевод",
        body=(
            f"{_when(row.created_at)}\n"
            f"{row.from_seller.name} → {row.to_seller.name}\n"
            f"{money}"
        ),
        can_undo=True,
    )


def _from_writeoff(row: StockWriteOff) -> JournalEntry:
    batch = row.batch
    qty = f"{row.quantity} шт"
    return JournalEntry(
        kind="writeoff",
        item_id=row.id,
        created_at=row.created_at,
        button=f"Списание · {_when(row.created_at)} · {batch.city.name} · {qty}",
        title="Списание",
        body=(
            f"{_when(row.created_at)}\n"
            f"{batch.city.name}\n"
            f"{_sku(batch.product)}\n"
            f"{qty} · закуп {format_money(batch.purchase_price)}"
        ),
        can_undo=True,
    )


def _from_withdraw(row: CashWithdrawal) -> JournalEntry:
    money = format_money(row.amount)
    return JournalEntry(
        kind="withdraw",
        item_id=row.id,
        created_at=row.created_at,
        button=f"Изъятие · {_when(row.created_at)} · {row.seller.name} · {money}",
        title="Изъятие",
        body=f"{_when(row.created_at)}\n{row.seller.name}\n{money}",
        can_undo=True,
    )


async def list_entries(session: AsyncSession) -> list[JournalEntry]:
    sales = await session.execute(
        select(Sale)
        .options(
            selectinload(Sale.seller),
            selectinload(Sale.batch).options(selectinload(Batch.city), _product_load()),
        )
        .order_by(Sale.created_at.desc())
        .limit(JOURNAL_LIMIT)
    )
    batches = await session.execute(
        select(Batch)
        .options(
            selectinload(Batch.city),
            selectinload(Batch.sales),
            _product_load(),
        )
        .order_by(Batch.created_at.desc())
        .limit(JOURNAL_LIMIT)
    )
    transfers = await session.execute(
        select(CashTransfer)
        .options(
            selectinload(CashTransfer.from_seller),
            selectinload(CashTransfer.to_seller),
        )
        .order_by(CashTransfer.created_at.desc())
        .limit(JOURNAL_LIMIT)
    )
    withdrawals = await session.execute(
        select(CashWithdrawal)
        .options(selectinload(CashWithdrawal.seller))
        .order_by(CashWithdrawal.created_at.desc())
        .limit(JOURNAL_LIMIT)
    )
    writeoffs = await session.execute(
        select(StockWriteOff)
        .options(
            selectinload(StockWriteOff.batch).options(
                selectinload(Batch.city),
                _product_load(),
            )
        )
        .order_by(StockWriteOff.created_at.desc())
        .limit(JOURNAL_LIMIT)
    )
    entries = (
        [_from_sale(row) for row in sales.scalars().all()]
        + [_from_batch(row) for row in batches.scalars().all()]
        + [_from_transfer(row) for row in transfers.scalars().all()]
        + [_from_withdraw(row) for row in withdrawals.scalars().all()]
        + [_from_writeoff(row) for row in writeoffs.scalars().all()]
    )
    entries.sort(key=lambda item: item.created_at, reverse=True)
    return entries[:JOURNAL_LIMIT]


async def get_entry(session: AsyncSession, kind: str, item_id: int) -> JournalEntry | None:
    if kind == "sale":
        sale = await session.get(
            Sale,
            item_id,
            options=[
                selectinload(Sale.seller),
                selectinload(Sale.batch).options(selectinload(Batch.city), _product_load()),
            ],
        )
        return _from_sale(sale) if sale else None
    if kind == "income":
        batch = await session.get(
            Batch,
            item_id,
            options=[
                selectinload(Batch.city),
                selectinload(Batch.sales),
                _product_load(),
            ],
        )
        return _from_batch(batch) if batch else None
    if kind == "transfer":
        row = await session.get(
            CashTransfer,
            item_id,
            options=[
                selectinload(CashTransfer.from_seller),
                selectinload(CashTransfer.to_seller),
            ],
        )
        return _from_transfer(row) if row else None
    if kind == "withdraw":
        row = await session.get(
            CashWithdrawal,
            item_id,
            options=[selectinload(CashWithdrawal.seller)],
        )
        return _from_withdraw(row) if row else None
    if kind == "writeoff":
        row = await session.get(
            StockWriteOff,
            item_id,
            options=[
                selectinload(StockWriteOff.batch).options(
                    selectinload(Batch.city),
                    _product_load(),
                )
            ],
        )
        return _from_writeoff(row) if row else None
    return None


async def undo_entry(session: AsyncSession, kind: str, item_id: int) -> None:
    entry = await get_entry(session, kind, item_id)
    if entry is None:
        raise CannotUndoError("Этой записи уже нет.")
    if not entry.can_undo:
        raise CannotUndoError(entry.block_reason or "Это уже нельзя отменить.")

    if kind == "sale":
        sale = await session.get(Sale, item_id)
        if sale is None:
            raise CannotUndoError("Этой записи уже нет.")
        try:
            await delete_sale(session, sale)
        except OutOfStockError as exc:
            raise CannotUndoError("Не получилось вернуть клюшки на партию.") from exc
        return
    if kind == "income":
        batch = await session.get(Batch, item_id, options=[selectinload(Batch.sales)])
        if batch is None:
            raise CannotUndoError("Этой записи уже нет.")
        if batch.sales:
            raise CannotUndoError("С этой партии уже продавали.")
        if batch.remaining_quantity != batch.quantity_in:
            raise CannotUndoError("С этой партии уже списывали.")
        product_id = batch.product_id
        await session.delete(batch)
        await session.flush()
        await catalog.remove_product_if_unused(session, product_id)
        return
    if kind == "transfer":
        row = await session.get(CashTransfer, item_id)
        if row is None:
            raise CannotUndoError("Этой записи уже нет.")
        await session.delete(row)
        return
    if kind == "withdraw":
        row = await session.get(CashWithdrawal, item_id)
        if row is None:
            raise CannotUndoError("Этой записи уже нет.")
        await session.delete(row)
        return
    if kind == "writeoff":
        row = await session.get(StockWriteOff, item_id)
        if row is None:
            raise CannotUndoError("Этой записи уже нет.")
        try:
            await delete_writeoff(session, row)
        except OutOfStockError as exc:
            raise CannotUndoError("Не получилось вернуть клюшки на партию.") from exc
        return
    raise CannotUndoError("Неизвестная операция.")
