from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import City, ColorOption, StickModel

DEFAULT_CITIES = ("Москва", "Санкт-Петербург", "Челябинск")
DEFAULT_COLOR_NAME = "Без цвета"


async def seed_cities(session: AsyncSession) -> None:
    existing = (await session.execute(select(City.name))).scalars().all()
    existing_names = set(existing)
    for name in DEFAULT_CITIES:
        if name not in existing_names:
            session.add(City(name=name))


async def ensure_default_color(session: AsyncSession, model: StickModel) -> ColorOption:
    existing = await session.scalar(
        select(ColorOption).where(
            ColorOption.model_id == model.id,
            ColorOption.is_default.is_(True),
        )
    )
    if existing is not None:
        return existing

    color = ColorOption(model_id=model.id, name=DEFAULT_COLOR_NAME, is_default=True)
    session.add(color)
    await session.flush()
    return color
