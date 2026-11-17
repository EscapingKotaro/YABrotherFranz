# app/api/webhooks.py
from fastapi import APIRouter, Request, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from arq.jobs import Job
import logging
from datetime import datetime, timezone

from app.database import get_session
from app.schemas.yandex_notification import (
    OrderCreatedNotificationDTO,
    OrderStatusUpdatedNotificationDTO,
)
from app.models.order import Order
from app.models.webhook import WebhookLog
from sqlalchemy import select
from app.services.clients.factory import get_yandex_client
from app.config import settings

router = APIRouter(prefix="/webhook/yandex", tags=["webhooks"])
logger = logging.getLogger(__name__)


@router.post("/{path:path}/notification")
async def receive_yandex_notification(
    path: str,
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """
    Универсальный endpoint для уведомлений Яндекса.
    Для цифровых товаров мы реагируем на ORDER_CREATED и сразу выдаем код.
    """
    payload_bytes = await request.body()
    
    try:
        import json
        raw_data = json.loads(payload_bytes)
        notification_type = raw_data.get("notificationType", "UNKNOWN")
        campaign_id = str(raw_data.get("campaignId", "unknown"))
        order_id = str(raw_data.get("orderId", "unknown"))
    except Exception as e:
        logger.error(f"[Webhook] Failed to parse notification: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    logger.info(f"[Webhook] Received {notification_type} for order {order_id}, campaign {campaign_id}")
    
    # Логируем вебхук в БД
    webhook_log = WebhookLog(
        campaign_id=campaign_id,
        order_id=order_id,
        webhook_type=notification_type,
        payload=raw_data,
        signature_valid=True,
        status="accepted",
    )
    session.add(webhook_log)
    await session.commit()
    
    # 1. Обработка PING (Яндекс проверяет, жив ли мы)
    if notification_type == "PING":
        return JSONResponse(
            status_code=200,
            content={
                "version": "1.0.0",
                "name": "yandex-market-client",
                "time": datetime.now(timezone.utc).isoformat()
            }
        )
    
    # 2. Обработка СОЗДАНИЯ ЗАКАЗА (ГЛАВНОЕ СОБЫТИЕ ДЛЯ ЦИФРЫ)
    if notification_type == "ORDER_CREATED":
        try:
            notification = OrderCreatedNotificationDTO(**raw_data)
            return await handle_order_created(session, request, notification)
        except Exception as e:
            logger.error(f"[Webhook] Error processing ORDER_CREATED: {e}")
            webhook_log.status = "error"
            webhook_log.error_message = str(e)
            await session.commit()
            raise HTTPException(status_code=500, detail=str(e))
    
    # 3. Обработка смены статуса (как фолбэк, если ORDER_CREATED потерялся)
    if notification_type == "ORDER_STATUS_UPDATED":
        try:
            notification = OrderStatusUpdatedNotificationDTO(**raw_data)
            return await handle_order_status_updated(session, request, notification)
        except Exception as e:
            logger.error(f"[Webhook] Error processing ORDER_STATUS_UPDATED: {e}")
            webhook_log.status = "error"
            webhook_log.error_message = str(e)
            await session.commit()
            raise HTTPException(status_code=500, detail=str(e))
    
    # Игнорируем остальные типы (отзывы, чаты и т.д.)
    return JSONResponse(status_code=200, content={"status": "ignored", "reason": "unknown_type"})


async def handle_order_created(
    session: AsyncSession,
    request: Request,
    notification: OrderCreatedNotificationDTO
) -> JSONResponse:
    """Запрашиваем полные данные у Яндекса, но не падаем, если их нет"""
    order_id = str(notification.orderId)
    campaign_id = str(notification.campaignId)
    
    # 1. Строгая идемпотентность
    existing_order = await session.execute(
        select(Order).where(Order.order_id == order_id)
    )
    order = existing_order.scalar_one_or_none()
    
    if order and order.status == "DELIVERED":
        logger.info(f"[Webhook] Order {order_id} already delivered. Ignoring retry.")
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": "already_delivered"})
    
    if order and order.status in ["PROCESSING", "RECEIVED"]:
        logger.info(f"[Webhook] Order {order_id} is already being processed. Ignoring retry.")
        return JSONResponse(status_code=200, content={"status": "accepted", "reason": "already_queued"})
    
    # 2. Данные по умолчанию из вебхука (если API Яндекса еще не готов)
    items_data = [item.model_dump() for item in notification.items]
    total_amount = 0.0
    currency = "RUB"
    created_at = datetime.now(timezone.utc)
    
    # 3. 🚀 ПЫТАЕМСЯ получить полные данные у Яндекса (best-effort)
    yandex_client = get_yandex_client()
    account = settings.accounts_by_campaign.get(campaign_id)
    
    if account:
        try:
            response = await yandex_client.get_orders2(
                business_id=account.business_id,
                order_ids=[int(order_id)],
                campaign_ids=[int(campaign_id)]
            )
            
            yandex_orders = response.get("orders", [])
            if yandex_orders:
                full_order_data = yandex_orders[0]
                items_data = full_order_data.get("items", items_data)
                total_payment = full_order_data.get("prices", {}).get("payment", {})
                total_amount = total_payment.get("value", 0.0)
                currency = total_payment.get("currencyId", "RUB")
                
                creation_date_str = full_order_data.get("creationDate")
                if creation_date_str:
                    try:
                        created_at = datetime.fromisoformat(creation_date_str.replace("Z", "+00:00"))
                    except Exception:
                        pass
                
                logger.info(f"[Webhook] ✅ Got full order details from Yandex API: {order_id}")
            else:
                logger.warning(f"[Webhook] ⚠️ Order {order_id} not yet in Yandex API (eventual consistency). Using webhook data.")
        except Exception as e:
            logger.warning(f"[Webhook] ⚠️ Failed to fetch from Yandex API: {e}. Using webhook data.")
    else:
        logger.warning(f"[Webhook] ⚠️ Unknown campaign_id: {campaign_id}. Using webhook data.")
    
    # 4. Создаем или обновляем запись в БД
    if not order:
        order = Order(
            order_id=order_id,
            campaign_id=campaign_id,
            status="PROCESSING",
            items_data=items_data,
            total_amount=total_amount,
            currency=currency,
            created_at=created_at,
        )
        session.add(order)
        await session.commit()
        logger.info(f"[Webhook] ✅ Created order record: {order_id}, Amount: {total_amount} {currency}")
    else:
        order.items_data = items_data
        order.total_amount = total_amount
        order.currency = currency
        order.status = "PROCESSING"
        await session.commit()

    # 5. СРАЗУ запускаем задачу на выдачу кода!
    logger.info(f"[Webhook] 🚀 Enqueueing 'process_order_task' with args: order_id={order_id}, campaign_id={campaign_id}")
    
    redis_pool = request.app.state.redis_pool
    job: Job = await redis_pool.enqueue_job(
        'process_order_task',
        order_id,
        campaign_id,
    )
    
    return JSONResponse(
        status_code=200,
        content={
            "status": "accepted",
            "order_id": order_id,
            "job_id": job.job_id,
        }
    )


async def handle_order_status_updated(
    session: AsyncSession,
    request: Request,
    notification: OrderStatusUpdatedNotificationDTO
) -> JSONResponse:
    """Фолбэк: если вдруг ORDER_CREATED не пришел, но пришел PROCESSING/STARTED"""
    order_id = str(notification.orderId)
    campaign_id = str(notification.campaignId)
    new_status = notification.status
    substatus = notification.substatus
    
    existing_order = await session.execute(
        select(Order).where(Order.order_id == order_id)
    )
    order = existing_order.scalar_one_or_none()
    
    if not order:
        # Создаем, если потеряли создание
        order = Order(
            order_id=order_id,
            campaign_id=campaign_id,
            status="PROCESSING",
            items_data=[], 
            created_at=datetime.now(timezone.utc),
        )
        session.add(order)
        await session.commit()
    
    if order.status == "DELIVERED":
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": "already_delivered"})
    
    # Если статус сменился на PROCESSING / STARTED и мы еще не выдали код
    if new_status == "PROCESSING" and substatus == "STARTED" and order.status != "PROCESSING":
        order.status = "PROCESSING"
        await session.commit()
        
        redis_pool = request.app.state.redis_pool
        job: Job = await redis_pool.enqueue_job('process_order_task', order_id, campaign_id)
        logger.info(f"[Webhook] 🚀 Enqueueing fulfillment from status update for order {order_id}")
        
        return JSONResponse(status_code=200, content={"status": "accepted", "job_id": job.job_id})
    
    # Если отменили
    if new_status == "CANCELLED":
        order.status = "CANCELLED"
        await session.commit()
        logger.info(f"[Webhook] Order {order_id} cancelled by Yandex")
        
    return JSONResponse(status_code=200, content={"status": "accepted", "new_status": new_status})