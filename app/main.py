# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from arq import create_pool
from arq.connections import RedisSettings
import logging

from app.config import settings
from app.database import init_db
from app.api.webhooks import router as webhooks_router
from app.admin.sqladmin_setup import setup_admin
from app.admin.dashboard import router as dashboard_router

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Starting Yandex Market Client...")
    
    # Инициализация БД
    await init_db()
    logger.info("✅ Database initialized")
    
    # Подключение к Redis
    app.state.redis_pool = await create_pool(RedisSettings.from_url(settings.redis_url))
    logger.info("✅ Redis connected")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down...")
    await app.state.redis_pool.close()


app = FastAPI(
    title="Yandex Market Client",
    description="Интеграционный сервис для Яндекс Маркета",
    version="1.0.0",
    lifespan=lifespan,
)

# Подключаем роутеры
app.include_router(webhooks_router)
app.include_router(dashboard_router)

# Подключаем админку
setup_admin(app)


@app.get("/")
async def root():
    return {
        "service": "Yandex Market Client",
        "version": "1.0.0",
        "docs": "/docs",
        "admin": "/admin",
        "dashboard": "/dashboard",
    }