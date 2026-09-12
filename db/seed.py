from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import City

DEFAULT_CITIES = ("Москва", "Санкт-Петербург", "Челябинск")


async def seed_cities(session: AsyncSession) -> None:
    existing = (await session.execute(select(City.name))).scalars().all()
    existing_names = set(existing)
    for name in DEFAULT_CITIES:
        if name not in existing_names:
            session.add(City(name=name))
