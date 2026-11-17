# app/admin/dashboard.py
import logging
from typing import Optional

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_session
from app.config import settings
from app.models.order import Order
from app.models.chat import Chat
from app.models.catalog import Listing
from app.services.clients.factory import get_yandex_client

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="app/admin/templates")


def ensure_admin(request: Request) -> Optional[RedirectResponse]:
    """
    Защита дашборда. Сессия 'authenticated' пишется SQLAdmin при логине.
    Если пользователь не залогинен — редирект на /admin/login.
    """
    if not request.session.get("authenticated", False):
        return RedirectResponse(url="/admin/login", status_code=302)
    return None


# Статусы карточек Яндекса: считаем опубликованными всё, что HAS_CARD_*
PUBLISHED_STATUSES = [
    "HAS_CARD_CAN_NOT_UPDATE",
    "HAS_CARD_CAN_UPDATE",
    "HAS_CARD_CAN_UPDATE_ERRORS",
    "HAS_CARD_CAN_UPDATE_PROCESSING",
]

STATUS_LABELS = {
    "HAS_CARD_CAN_NOT_UPDATE": "Карточка Маркета (нельзя менять)",
    "HAS_CARD_CAN_UPDATE": "Можно дополнить",
    "HAS_CARD_CAN_UPDATE_ERRORS": "Изменения не приняты",
    "HAS_CARD_CAN_UPDATE_PROCESSING": "Изменения на проверке",
    "NO_CARD_NEED_CONTENT": "Создайте карточку",
    "NO_CARD_MARKET_WILL_CREATE": "Создаст Маркет",
    "NO_CARD_ERRORS": "Не создана (ошибка)",
    "NO_CARD_PROCESSING": "Проверяем данные",
    "NO_CARD_ADD_TO_CAMPAIGN": "Разместите в магазине",
}


def _extract_card(item: dict) -> dict:
    """Вытаскиваем offerId, name, статус из элемента offer-mappings (поле может быть в offer или mapping)."""
    offer = item.get("offer", {}) or {}
    mapping = item.get("mapping", {}) or {}
    card_status = (
        item.get("cardStatus")
        or mapping.get("cardStatus")
        or offer.get("cardStatus")
        or "UNKNOWN"
    )
    return {
        "offerId": offer.get("offerId", "-"),
        "name": offer.get("name", "-"),
        "vendor": offer.get("vendor", "-"),
        "marketCategoryId": offer.get("marketCategoryId", "-"),
        "downloadable": offer.get("downloadable", False),
        "cardStatus": card_status,
        "cardStatusLabel": STATUS_LABELS.get(card_status, card_status),
        "isPublished": str(card_status).startswith("HAS_CARD"),
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    # 🔥 ЗАЩИТА
    redirect = ensure_admin(request)
    if redirect:
        return redirect

    orders_total = (await session.execute(select(func.count(Order.id)))).scalar() or 0
    orders_delivered = (await session.execute(
        select(func.count(Order.id)).where(Order.status == "DELIVERED")
    )).scalar() or 0
    orders_failed = (await session.execute(
        select(func.count(Order.id)).where(Order.status == "FAILED_FULFILLMENT")
    )).scalar() or 0
    orders_pending = (await session.execute(
        select(func.count(Order.id)).where(Order.status.in_(["RECEIVED", "PROCESSING", "DELIVERY_PENDING"]))
    )).scalar() or 0
    chats_active = (await session.execute(
        select(func.count(Chat.id)).where(Chat.is_active == True)
    )).scalar() or 0
    listings_published = (await session.execute(
        select(func.count(Listing.id)).where(Listing.status == "published")
    )).scalar() or 0
    listings_errors = (await session.execute(
        select(func.count(Listing.id)).where(Listing.consecutive_error_count > 0)
    )).scalar() or 0

    recent_orders = (await session.execute(
        select(Order).order_by(Order.created_at.desc()).limit(10)
    )).scalars().all()

    error_listings = (await session.execute(
        select(Listing).where(Listing.consecutive_error_count > 0).order_by(Listing.updated_at.desc()).limit(10)
    )).scalars().all()

    redis_pool = request.app.state.redis_pool
    queue_stats = {}
    try:
        for queue_name in ["fulfillment", "catalog", "chat", "dlq"]:
            queue_stats[queue_name] = await redis_pool.llen(f"arq:queue:{queue_name}")
    except Exception as e:
        logger.error(f"[Dashboard] Failed to read Redis queues: {e}")
        queue_stats = {"error": str(e)}

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
        },
    )


@router.get("/yandex-catalog", response_class=HTMLResponse)
async def yandex_catalog(
    request: Request,
    business_id: Optional[str] = None,
    page_token: Optional[str] = None,
    only_published: bool = True,
):
    """
    Реальные карточки в каталоге Яндекса (offer-mappings).
    only_published=true -> фильтр по HAS_CARD_*
    """
    redirect = ensure_admin(request)
    if redirect:
        return redirect

    # Определяем бизнес
    if not settings.yandex_accounts:
        return templates.TemplateResponse(
            "yandex_catalog.html",
            {"request": request, "error": "Нет настроенных аккаунтов Яндекса", "cards": [], "next_page_token": None},
        )

    acc = None
    if business_id:
        acc = next((a for a in settings.yandex_accounts if a.business_id == business_id), None)
    if not acc:
        acc = settings.yandex_accounts[0]
        business_id = acc.business_id

    yandex_client = get_yandex_client()
    statuses = PUBLISHED_STATUSES if only_published else None

    error_msg = None
    cards = []
    next_page_token = None

    try:
        resp = await yandex_client.get_offer_mappings(
            business_id=business_id,
            limit=100,
            page_token=page_token,
            card_statuses=statuses,
        )
        items = resp.get("result", {}).get("offerMappings", [])
        cards = [_extract_card(it) for it in items]
        next_page_token = (resp.get("result", {}).get("paging") or {}).get("nextPageToken")
    except Exception as e:
        logger.error(f"[Dashboard] offer-mappings failed: {e}")
        error_msg = str(e)

    return templates.TemplateResponse(
        "yandex_catalog.html",
        {
            "request": request,
            "business_id": business_id,
            "campaign_id": acc.campaign_id,
            "cards": cards,
            "next_page_token": next_page_token,
            "only_published": only_published,
            "error": error_msg,
            "is_mock": settings.mock_yandex,
        },
    )