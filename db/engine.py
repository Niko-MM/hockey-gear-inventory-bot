from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from db.models import Base
from db.seed import seed_cities

db_file = Path(settings.db_path)
engine = create_async_engine(
    f"sqlite+aiosqlite:///{db_file.resolve()}",
    echo=False,
)


@event.listens_for(engine.sync_engine, "connect")
def _enable_sqlite_fk(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    db_file.parent.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_session_maker() as session:
        await seed_cities(session)
        await session.commit()
