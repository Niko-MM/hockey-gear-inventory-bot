from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Batch, City, IncomeImport


async def list_cities(session: AsyncSession) -> list[City]:
    result = await session.execute(select(City).order_by(City.name))
    return list(result.scalars().all())


async def create_batch(
    session: AsyncSession,
    *,
    product_id: int,
    city_id: int,
    quantity: int,
    purchase_price: Decimal,
    import_id: int | None = None,
) -> Batch:
    batch = Batch(
        product_id=product_id,
        city_id=city_id,
        purchase_price=purchase_price,
        quantity_in=quantity,
        remaining_quantity=quantity,
        import_id=import_id,
    )
    session.add(batch)
    await session.flush()
    return batch


async def create_income_import(session: AsyncSession, city_id: int) -> IncomeImport:
    row = IncomeImport(city_id=city_id)
    session.add(row)
    await session.flush()
    return row


def _second_key(moment) -> object:
    if moment is None:
        return None
    return moment.replace(microsecond=0)


async def group_legacy_imports(session: AsyncSession) -> None:
    result = await session.execute(
        select(Batch).where(Batch.import_id.is_(None)).order_by(Batch.id)
    )
    batches = list(result.scalars().all())
    groups: dict[tuple, list[Batch]] = {}
    for batch in batches:
        key = (batch.city_id, _second_key(batch.created_at))
        groups.setdefault(key, []).append(batch)
    for (city_id, _), members in groups.items():
        if len(members) < 2:
            continue
        pack = IncomeImport(city_id=city_id, created_at=members[0].created_at)
        session.add(pack)
        await session.flush()
        for member in members:
            member.import_id = pack.id
    await session.flush()
