# app/api/webhooks.py
from fastapi import APIRouter, Request, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from arq.jobs import Job
import logging
from datetime import datetime, timezone

from app.database import get_session
from app.schemas.yandex_notification import (
    YandexNotificationDTO,
    PingNotificationDTO,
    OrderCreatedNotificationDTO,
    OrderStatusUpdatedNotificationDTO,
)
from app.models.order import Order
from app.models.webhook import WebhookLog
from app.services.yandex_webhook_validator import YandexWebhookValidator
from sqlalchemy import select

router = APIRouter(prefix="/webhook/yandex", tags=["webhooks"])
logger = logging.getLogger(__name__)


@router.post("/{path:path}/notification")
async def receive_yandex_notification(
    path: str,
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """
    Универсальный endpoint для всех уведомлений от Яндекс Маркета.
    
    Яндекс сам добавляет /notification к URL, который мы указали в кабинете.
    Поэтому мы ловим всё по пути /webhook/yandex/{path}/notification.
    
    Обрабатываем:
    - PING — проверочное уведомление
    - ORDER_CREATED — создан новый заказ
    - ORDER_STATUS_UPDATED — изменён статус заказа
    """
    
    # 1. Читаем raw body
    payload_bytes = await request.body()
    
    # 2. Парсим тип уведомления (нужно для логирования и валидации)
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
    
    # 3. Записываем в лог вебхуков
    webhook_log = WebhookLog(
        campaign_id=campaign_id,
        order_id=order_id,
        webhook_type=notification_type,
        payload=raw_data,
        signature_valid=True,  # TODO: добавить проверку подписи
        status="accepted",
    )
    session.add(webhook_log)
    await session.commit()
    
    # 4. Обработка PING
    if notification_type == "PING":
        logger.info(f"[Webhook] PING received, responding with 200")
        return JSONResponse(
            status_code=200,
            content={
                "version": "1.0.0",
                "name": "yandex-market-client",
                "time": datetime.now(timezone.utc).isoformat()
            }
        )
    
    # 5. Обработка ORDER_CREATED
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
    
    # 6. Обработка ORDER_STATUS_UPDATED
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
    
    # 7. Неизвестный тип уведомления
    logger.warning(f"[Webhook] Unknown notification type: {notification_type}")
    return JSONResponse(status_code=200, content={"status": "ignored", "reason": "unknown_type"})


async def handle_order_created(
    session: AsyncSession,
    request: Request,
    notification: OrderCreatedNotificationDTO
) -> JSONResponse:
    """Обработка уведомления о создании заказа"""
    order_id = str(notification.orderId)
    campaign_id = str(notification.campaignId)
    
    logger.info(f"[Webhook] Processing ORDER_CREATED: order={order_id}, campaign={campaign_id}")
    
    # Проверяем идемпотентность
    existing_order = await session.execute(
        select(Order).where(Order.order_id == order_id)
    )
    order = existing_order.scalar_one_or_none()
    
    if order and order.status == "DELIVERED":
        logger.info(f"[Webhook] Order {order_id} already delivered, skipping")
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": "already_delivered"})
    
    # Создаём или обновляем запись о заказе
    if not order:
        order = Order(
            order_id=order_id,
            campaign_id=campaign_id,
            status="RECEIVED",
            items_data=[item.model_dump() for item in notification.items],
            created_at=datetime.now(timezone.utc),
        )
        session.add(order)
        await session.commit()
        logger.info(f"[Webhook] Created order record: {order_id}")
    
    # Ставим задачу в очередь (фулфилмент запустится, когда статус станет PROCESSING)
    # Пока просто логируем, что заказ создан
    logger.info(f"[Webhook] Order {order_id} created, waiting for PROCESSING status")
    
    return JSONResponse(
        status_code=200,
        content={
            "status": "accepted",
            "order_id": order_id,
            "campaign_id": campaign_id,
        }
    )


async def handle_order_status_updated(
    session: AsyncSession,
    request: Request,
    notification: OrderStatusUpdatedNotificationDTO
) -> JSONResponse:
    """Обработка уведомления об изменении статуса заказа"""
    order_id = str(notification.orderId)
    campaign_id = str(notification.campaignId)
    new_status = notification.status
    substatus = notification.substatus
    
    logger.info(f"[Webhook] Processing ORDER_STATUS_UPDATED: order={order_id}, status={new_status}, substatus={substatus}")
    
    # Находим заказ в БД
    existing_order = await session.execute(
        select(Order).where(Order.order_id == order_id)
    )
    order = existing_order.scalar_one_or_none()
    
    # Если заказа нет в БД — создаём (могли пропустить ORDER_CREATED)
    if not order:
        logger.warning(f"[Webhook] Order {order_id} not found in DB, creating from status update")
        order = Order(
            order_id=order_id,
            campaign_id=campaign_id,
            status="RECEIVED",
            items_data=[],  # Нет данных о товарах, нужно будет подтянуть через API
            created_at=datetime.now(timezone.utc),
        )
        session.add(order)
        await session.commit()
    
    # Если заказ уже доставлен — игнорируем
    if order.status == "DELIVERED":
        logger.info(f"[Webhook] Order {order_id} already delivered, skipping status update")
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": "already_delivered"})
    
    # Обновляем статус
    old_status = order.status
    order.status = new_status
    await session.commit()
    
    logger.info(f"[Webhook] Order {order_id} status changed: {old_status} -> {new_status}")
    
    # Если статус PROCESSING и подстатус STARTED — запускаем фулфилмент
    if new_status == "PROCESSING" and substatus == "STARTED":
        logger.info(f"[Webhook] Order {order_id} is ready for fulfillment, enqueueing...")
        
        redis_pool = request.app.state.redis_pool
        job: Job = await redis_pool.enqueue_job(
            'process_order_task',
            order_id,
            campaign_id,
        )
        
        logger.info(f"[Webhook] Enqueued fulfillment for order {order_id}, job_id={job.job_id}")
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "accepted",
                "order_id": order_id,
                "job_id": job.job_id,
            }
        )
    
    # Другие статусы просто логируем
    return JSONResponse(
        status_code=200,
        content={
            "status": "accepted",
            "order_id": order_id,
            "new_status": new_status,
        }
    )


@router.get("/health")
async def health_check():
    """Healthcheck для Docker/K8s"""
    return {"status": "ok"}