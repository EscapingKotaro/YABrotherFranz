# app/api/yandex_sync.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import logging

from app.database import get_session
from app.models.order import Order
from app.models.catalog import Listing
from app.config import settings
from app.services.clients.factory import get_yandex_client

router = APIRouter(prefix="/api/yandex", tags=["yandex_sync"])
logger = logging.getLogger(__name__)


@router.get("/orders")
async def get_yandex_orders(
    campaign_id: str = None,
    status: str = "PROCESSING",
    limit: int = 50,
    session: AsyncSession = Depends(get_session)
):
    """
    Получает заказы из Яндекс Маркета и показывает их.
    """
    yandex_client = get_yandex_client()
    
    # Если campaign_id не передан, берём первый из конфига
    if not campaign_id:
        if not settings.yandex_accounts:
            raise HTTPException(status_code=400, detail="No Yandex accounts configured")
        campaign_id = settings.yandex_accounts[0].campaign_id
    
    # Находим business_id по campaign_id
    account = settings.accounts_by_campaign.get(campaign_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")
    
    # Запрашиваем заказы из Яндекса
    try:
        response = await yandex_client.get_orders(
            business_id=account.business_id,
            campaign_ids=[campaign_id],
            statuses=[status],
            limit=limit,
        )
        
        orders = response.get("result", {}).get("orders", [])
        
        return {
            "success": True,
            "campaign_id": campaign_id,
            "status": status,
            "count": len(orders),
            "orders": orders,
        }
    except Exception as e:
        logger.error(f"[YandexSync] Error fetching orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/listings")
async def get_local_listings(
    status: str = "published",
    limit: int = 100,
    session: AsyncSession = Depends(get_session)
):
    """
    Показывает наши локальные listings (карточки) из БД.
    """
    query = select(Listing).where(Listing.status == status).limit(limit)
    result = await session.execute(query)
    listings = result.scalars().all()
    
    return {
        "success": True,
        "status": status,
        "count": len(listings),
        "listings": [
            {
                "id": l.id,
                "external_id": l.external_id,
                "channel_id": l.channel_id,
                "status": l.status,
                "reported_price_amount": l.reported_price_amount,
                "reported_price_currency": l.reported_price_currency,
                "presentation_title": l.presentation_title,
                "consecutive_error_count": l.consecutive_error_count,
                "updated_at": l.updated_at.isoformat() if l.updated_at else None,
            }
            for l in listings
        ],
    }


@router.get("/dashboard-stats")
async def get_dashboard_stats(
    session: AsyncSession = Depends(get_session)
):
    """
    Возвращает статистику для дашборда.
    """
    # Считаем заказы
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
    
    # Считаем listings
    listings_published = await session.execute(
        select(func.count(Listing.id)).where(Listing.status == "published")
    )
    listings_published = listings_published.scalar() or 0
    
    listings_errors = await session.execute(
        select(func.count(Listing.id)).where(Listing.consecutive_error_count > 0)
    )
    listings_errors = listings_errors.scalar() or 0
    
    return {
        "success": True,
        "orders_total": orders_total,
        "orders_delivered": orders_delivered,
        "orders_failed": orders_failed,
        "listings_published": listings_published,
        "listings_errors": listings_errors,
    }