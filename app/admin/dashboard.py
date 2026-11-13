# app/admin/dashboard.py
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import logging

from app.database import get_session
from app.models.order import Order
from app.models.chat import Chat, ChatMessage
from app.models.catalog import Listing

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="app/admin/templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """Главная страница дашборда"""
    
    # Считаем метрики из БД
    orders_total = await session.execute(select(func.count(Order.id)))
    orders_total = orders_total.scalar() or 0
    
    orders_delivered = await session.execute(
        select(func.count(Order.id)).where(Order.status == "DELIVERED")
    )
    orders_delivered = orders_delivered.scalar() or 0
    
    orders_failed = await session.execute(
        select(func.count(Order.id)).where(Order.status == "FAILED_FULFILLMENT")
    )
    orders_failed = orders_failed.scalar() or 0
    
    orders_pending = await session.execute(
        select(func.count(Order.id)).where(Order.status.in_(["RECEIVED", "PROCESSING"]))
    )
    orders_pending = orders_pending.scalar() or 0
    
    chats_active = await session.execute(
        select(func.count(Chat.id)).where(Chat.is_active == True)
    )
    chats_active = chats_active.scalar() or 0
    
    listings_published = await session.execute(
        select(func.count(Listing.id)).where(Listing.status == "published")
    )
    listings_published = listings_published.scalar() or 0
    
    listings_errors = await session.execute(
        select(func.count(Listing.id)).where(Listing.consecutive_error_count > 0)
    )
    listings_errors = listings_errors.scalar() or 0
    
    # Последние 10 заказов
    recent_orders_result = await session.execute(
        select(Order).order_by(Order.created_at.desc()).limit(10)
    )
    recent_orders = recent_orders_result.scalars().all()
    
    # Последние 10 ошибок
    error_listings_result = await session.execute(
        select(Listing).where(Listing.consecutive_error_count > 0).order_by(Listing.updated_at.desc()).limit(10)
    )
    error_listings = error_listings_result.scalars().all()
    
    # Читаем длины очередей из Redis
    redis_pool = request.app.state.redis_pool
    queue_stats = {}
    
    try:
        # ARQ хранит очереди в Redis ключах arq:queue:{name}
        for queue_name in ['fulfillment', 'catalog', 'chat', 'dlq']:
            queue_key = f"arq:queue:{queue_name}"
            queue_length = await redis_pool.llen(queue_key)
            queue_stats[queue_name] = queue_length
    except Exception as e:
        logger.error(f"[Dashboard] Failed to read Redis queues: {e}")
        queue_stats = {"error": str(e)}

    queue_stats = {}
    try:
        redis_pool = request.app.state.redis_pool
        for queue_name in ['arq:queue:fulfillment', 'arq:queue:catalog', 'arq:queue:chat', 'arq:queue:default']:
            length = await redis_pool.llen(queue_name)
            queue_stats[queue_name.replace('arq:queue:', '')] = length
    except Exception as e:
        queue_stats = {"error": str(e)}

    # 2. Последние 10 вебхуков
    recent_webhooks_result = await session.execute(
        select(WebhookLog).order_by(WebhookLog.created_at.desc()).limit(10)
    )
    recent_webhooks = recent_webhooks_result.scalars().all()
    
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "orders_total": orders_total,
            "orders_delivered": orders_delivered,
            "orders_failed": orders_failed,
            "orders_pending": orders_pending,
            "chats_active": chats_active,
            "listings_published": listings_published,
            "listings_errors": listings_errors,
            "recent_orders": recent_orders,
            "error_listings": error_listings,
            "queue_stats": queue_stats,
        "queue_stats": queue_stats,
        "recent_webhooks": recent_webhooks,
        }
    )
