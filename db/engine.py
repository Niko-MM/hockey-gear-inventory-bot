from pathlib import Path

from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from db.models import Base
from db.seed import seed_cities
from repositories.batches import group_legacy_imports

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


def _migrate_schema(sync_conn) -> None:
    Base.metadata.create_all(sync_conn)
    inspector = inspect(sync_conn)
    tables = inspector.get_table_names()
    if "sales" in tables:
        columns = {column["name"] for column in inspector.get_columns("sales")}
        if "seller_id" not in columns:
            sync_conn.execute(text("ALTER TABLE sales ADD COLUMN seller_id INTEGER REFERENCES sellers(id)"))
    if "batches" in tables:
        columns = {column["name"] for column in inspector.get_columns("batches")}
        if "import_id" not in columns:
            sync_conn.execute(
                text("ALTER TABLE batches ADD COLUMN import_id INTEGER REFERENCES income_imports(id)")
            )


async def init_db() -> None:
    db_file.parent.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as connection:
        await connection.run_sync(_migrate_schema)
    async with async_session_maker() as session:
        await seed_cities(session)
        await group_legacy_imports(session)
        await session.commit()
