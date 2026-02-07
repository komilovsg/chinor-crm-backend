"""Async engine и сессия SQLAlchemy (asyncpg)."""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.models import Base

_settings = Settings()

# Для async нужен драйвер asyncpg: postgresql:// -> postgresql+asyncpg://
database_url = _settings.database_url
if database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(
    database_url,
    echo=False,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Зависимость FastAPI: одна сессия на запрос. Коммит выполняет вызывающий код."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Создание таблиц (для тестов или если не используем Alembic). Не вызывать при наличии миграций."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
