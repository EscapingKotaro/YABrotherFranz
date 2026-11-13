# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from arq import create_pool
from arq.connections import RedisSettings
import logging
from urllib.parse import urlparse

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
    logger.info("🚀 Starting Yandex Market Client...")
    await init_db()
    logger.info("✅ Database initialized")

    parsed = urlparse(settings.redis_url)
    redis_settings = RedisSettings(host=parsed.hostname or "redis", port=parsed.port or 6379, database=int(parsed.path.lstrip('/') or 0), password=parsed.password)
    app.state.redis_pool = await create_pool(redis_settings)
    logger.info("✅ Redis connected")

    yield

    logger.info("🛑 Shutting down...")
    await app.state.redis_pool.close()

app = FastAPI(title="Yandex Market Client", version="1.0.0", lifespan=lifespan)

# 🔥 ДОБАВЛЯЕМ MIDDLEWARE ДЛЯ СЕССИЙ (нужен для логина в админку)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    https_only=False, # Поменяй на True, когда будет HTTPS
)

app.include_router(webhooks_router)
app.include_router(dashboard_router)
setup_admin(app)

@app.get("/")
async def root():
    return {"service": "Yandex Market Client", "admin": "/admin"}
