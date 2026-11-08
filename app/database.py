# app/database.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

# Создаем движок
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

# Создаем фабрику сессий
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Базовый класс для всех моделей"""
    pass


async def get_session() -> AsyncSession:
    """Dependency для FastAPI: получение сессии БД"""
    async with async_session_factory() as session:
        yield session


async def init_db():
    """Создание всех таблиц (для разработки, в проде используем Alembic)"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)