from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import Batch, CashDeposit, CashTransfer, CashWithdrawal, IncomeImport, Product, Sale, StockWriteOff
from repositories import catalog
from utils.labels import color_title
from repositories.sales import OutOfStockError, delete_sale
from repositories.sellers import InsufficientFundsError, delete_deposit
from repositories.writeoffs import delete_writeoff
from utils.dates import as_local, period_utc_bounds
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
    return as_local(moment).strftime("%d.%m %H:%M")


def _color_title(color) -> str:
    return color_title(color)


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
            f"{batch.city.name} · {batch.product.model.name} · {batch.quantity_in} шт"
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


def _from_pack(members: list[Batch]) -> JournalEntry:
    ordered = sorted(members, key=lambda item: (_sku(item.product), item.id))
    first = ordered[0]
    city = first.city.name
    total_qty = sum(item.quantity_in for item in ordered)
    total_cost = sum((item.purchase_price * item.quantity_in for item in ordered), Decimal("0"))
    sold = any(bool(item.sales) for item in ordered)
    written = any(
        item.remaining_quantity != item.quantity_in and not item.sales for item in ordered
    )
    if sold and written:
        block_reason = "С части партий уже продавали или списывали."
    elif sold:
        block_reason = "С части партий уже продавали."
    elif written:
        block_reason = "С части партий уже списывали."
    else:
        block_reason = ""
    lines = [
        _when(first.created_at),
        city,
        f"{len(ordered)} партий · {total_qty} шт · закуп {format_money(total_cost)}",
        "",
    ]
    lines.extend(
        f"{_sku(item.product)} — {item.quantity_in} шт · {format_money(item.purchase_price)}"
        for item in ordered
    )
    return JournalEntry(
        kind="income_pack",
        item_id=first.import_id or 0,
        created_at=first.created_at,
        button=(
            f"Поступление · {_when(first.created_at)} · {city} · "
            f"{len(ordered)} парт. · {total_qty} шт"
        ),
        title="Поступление",
        body="\n".join(lines),
        can_undo=not sold and not written,
        block_reason=block_reason,
    )


def _batch_entries(rows: list[Batch]) -> list[JournalEntry]:
    packs: dict[int, list[Batch]] = {}
    singles: list[Batch] = []
    for batch in rows:
        if batch.import_id is None:
            singles.append(batch)
            continue
        packs.setdefault(batch.import_id, []).append(batch)
    entries = [_from_batch(item) for item in singles]
    for members in packs.values():
        if len(members) == 1:
            entries.append(_from_batch(members[0]))
        else:
            entries.append(_from_pack(members))
    return entries


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


def _from_deposit(row: CashDeposit) -> JournalEntry:
    money = format_money(row.amount)
    return JournalEntry(
        kind="deposit",
        item_id=row.id,
        created_at=row.created_at,
        button=f"Опт · {_when(row.created_at)} · {row.seller.name} · {money}",
        title="Опт",
        body=f"{_when(row.created_at)}\n{row.seller.name}\n{money}",
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


def _period_filter(column, start, end):
    begin, finish = period_utc_bounds(start, end)
    return column >= begin, column < finish


async def list_entries(session: AsyncSession) -> list[JournalEntry]:
    entries = await _collect_entries(session, limit=JOURNAL_LIMIT)
    entries.sort(key=lambda item: item.created_at, reverse=True)
    return entries[:JOURNAL_LIMIT]


async def list_period(
    session: AsyncSession,
    start: date,
    end: date,
    *,
    page: int = 0,
) -> tuple[list[JournalEntry], int]:
    entries = await _collect_entries(
        session,
        sale_filters=_period_filter(Sale.created_at, start, end),
        batch_filters=_period_filter(Batch.created_at, start, end),
        transfer_filters=_period_filter(CashTransfer.created_at, start, end),
        withdraw_filters=_period_filter(CashWithdrawal.created_at, start, end),
        deposit_filters=_period_filter(CashDeposit.created_at, start, end),
        writeoff_filters=_period_filter(StockWriteOff.created_at, start, end),
    )
    entries.sort(key=lambda item: item.created_at, reverse=True)
    total = len(entries)
    if total == 0:
        return [], 0
    pages = (total + JOURNAL_LIMIT - 1) // JOURNAL_LIMIT
    page = min(max(page, 0), pages - 1)
    offset = page * JOURNAL_LIMIT
    return entries[offset : offset + JOURNAL_LIMIT], total


async def _collect_entries(
    session: AsyncSession,
    *,
    sale_filters=(),
    batch_filters=(),
    transfer_filters=(),
    withdraw_filters=(),
    deposit_filters=(),
    writeoff_filters=(),
    limit: int | None = None,
) -> list[JournalEntry]:
    sales_stmt = (
        select(Sale)
        .options(
            selectinload(Sale.seller),
            selectinload(Sale.batch).options(selectinload(Batch.city), _product_load()),
        )
        .order_by(Sale.created_at.desc())
    )
    if sale_filters:
        sales_stmt = sales_stmt.where(*sale_filters)
    batches_stmt = (
        select(Batch)
        .options(
            selectinload(Batch.city),
            selectinload(Batch.sales),
            _product_load(),
        )
        .order_by(Batch.created_at.desc())
    )
    if batch_filters:
        batches_stmt = batches_stmt.where(*batch_filters)
    transfers_stmt = (
        select(CashTransfer)
        .options(
            selectinload(CashTransfer.from_seller),
            selectinload(CashTransfer.to_seller),
        )
        .order_by(CashTransfer.created_at.desc())
    )
    if transfer_filters:
        transfers_stmt = transfers_stmt.where(*transfer_filters)
    withdrawals_stmt = (
        select(CashWithdrawal)
        .options(selectinload(CashWithdrawal.seller))
        .order_by(CashWithdrawal.created_at.desc())
    )
    if withdraw_filters:
        withdrawals_stmt = withdrawals_stmt.where(*withdraw_filters)
    deposits_stmt = (
        select(CashDeposit)
        .options(selectinload(CashDeposit.seller))
        .order_by(CashDeposit.created_at.desc())
    )
    if deposit_filters:
        deposits_stmt = deposits_stmt.where(*deposit_filters)
    writeoffs_stmt = (
        select(StockWriteOff)
        .options(
            selectinload(StockWriteOff.batch).options(
                selectinload(Batch.city),
                _product_load(),
            )
        )
        .order_by(StockWriteOff.created_at.desc())
    )
    if writeoff_filters:
        writeoffs_stmt = writeoffs_stmt.where(*writeoff_filters)
    if limit is not None:
        sales_stmt = sales_stmt.limit(limit)
        batches_stmt = batches_stmt.limit(limit)
        transfers_stmt = transfers_stmt.limit(limit)
        withdrawals_stmt = withdrawals_stmt.limit(limit)
        deposits_stmt = deposits_stmt.limit(limit)
        writeoffs_stmt = writeoffs_stmt.limit(limit)

    sales = await session.execute(sales_stmt)
    batches = await session.execute(batches_stmt)
    transfers = await session.execute(transfers_stmt)
    withdrawals = await session.execute(withdrawals_stmt)
    deposits = await session.execute(deposits_stmt)
    writeoffs = await session.execute(writeoffs_stmt)
    batch_rows = list(batches.scalars().all())
    import_ids = {row.import_id for row in batch_rows if row.import_id is not None}
    if import_ids:
        extra = await session.execute(
            select(Batch)
            .options(
                selectinload(Batch.city),
                selectinload(Batch.sales),
                _product_load(),
            )
            .where(Batch.import_id.in_(import_ids))
        )
        by_id = {row.id: row for row in batch_rows}
        for row in extra.scalars().all():
            by_id[row.id] = row
        batch_rows = list(by_id.values())
    return (
        [_from_sale(row) for row in sales.scalars().all()]
        + _batch_entries(batch_rows)
        + [_from_transfer(row) for row in transfers.scalars().all()]
        + [_from_withdraw(row) for row in withdrawals.scalars().all()]
        + [_from_deposit(row) for row in deposits.scalars().all()]
        + [_from_writeoff(row) for row in writeoffs.scalars().all()]
    )


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
    if kind == "income_pack":
        result = await session.execute(
            select(Batch)
            .options(
                selectinload(Batch.city),
                selectinload(Batch.sales),
                _product_load(),
            )
            .where(Batch.import_id == item_id)
        )
        members = list(result.scalars().all())
        return _from_pack(members) if members else None
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
    if kind == "deposit":
        row = await session.get(
            CashDeposit,
            item_id,
            options=[selectinload(CashDeposit.seller)],
        )
        return _from_deposit(row) if row else None
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
    if kind == "income_pack":
        result = await session.execute(
            select(Batch)
            .options(selectinload(Batch.sales))
            .where(Batch.import_id == item_id)
        )
        members = list(result.scalars().all())
        if not members:
            raise CannotUndoError("Этой записи уже нет.")
        if any(item.sales for item in members):
            raise CannotUndoError("С части партий уже продавали.")
        if any(item.remaining_quantity != item.quantity_in for item in members):
            raise CannotUndoError("С части партий уже списывали.")
        product_ids = {item.product_id for item in members}
        for item in members:
            await session.delete(item)
        pack = await session.get(IncomeImport, item_id)
        if pack is not None:
            await session.delete(pack)
        await session.flush()
        for product_id in product_ids:
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
    if kind == "deposit":
        row = await session.get(CashDeposit, item_id)
        if row is None:
            raise CannotUndoError("Этой записи уже нет.")
        try:
            await delete_deposit(session, row)
        except InsufficientFundsError as exc:
            raise CannotUndoError("В кассе уже меньше, чем зачисляли.") from exc
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
