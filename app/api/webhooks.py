# app/api/webhooks.py
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from arq.jobs import Job
import logging
from datetime import datetime, timezone

from app.database import get_session
from app.config import settings
from app.schemas.yandex_notification import (
    OrderCreatedNotificationDTO,
    OrderStatusUpdatedNotificationDTO,
)
from app.models.order import Order
from app.models.webhook import WebhookLog
from app.services.clients.factory import get_yandex_client
from sqlalchemy import select

router = APIRouter(prefix="/webhook/yandex", tags=["webhooks"])
logger = logging.getLogger(__name__)

# 🔥 Константы для валидного ответа Яндексу (см. доку: name/version 1-100 симв.)
INTEGRATION_NAME = "yandex-market-client"
INTEGRATION_VERSION = "1.0.0"


def yandex_ok() -> JSONResponse:
    """
    Универсальный валидный ответ Яндексу на уведомление.
    Схема из доки: {version, name, time}. time — ISO 8601 с суффиксом Z, без микросекунд.
    """
    return JSONResponse(
        status_code=200,
        content={
            "version": INTEGRATION_VERSION,
            "name": INTEGRATION_NAME,
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        },
    )


@router.post("/{path:path}/notification")
async def receive_yandex_notification(
    path: str,
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    payload_bytes = await request.body()

    try:
        import json
        raw_data = json.loads(payload_bytes)
        notification_type = raw_data.get("notificationType", "UNKNOWN")
        campaign_id = str(raw_data.get("campaignId", "unknown"))
        order_id = str(raw_data.get("orderId", "unknown"))
    except Exception as e:
        logger.error(f"[Webhook] Failed to parse notification: {e}")
        # Некорректное уведомление от Яндекса -> 400 по доке
        raise HTTPException(status_code=400, detail="Invalid JSON")

    logger.info(f"[Webhook] Received {notification_type} for order {order_id}, campaign {campaign_id}")

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

    # PING
    if notification_type == "PING":
        logger.info("[Webhook] PING received")
        return yandex_ok()

    # ORDER_CREATED
    if notification_type == "ORDER_CREATED":
        try:
            notification = OrderCreatedNotificationDTO(**raw_data)
            return await handle_order_created(session, request, notification)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[Webhook] Error processing ORDER_CREATED: {e}")
            webhook_log.status = "error"
            webhook_log.error_message = str(e)
            await session.commit()
            raise HTTPException(status_code=500, detail=str(e))

    # ORDER_STATUS_UPDATED
    if notification_type == "ORDER_STATUS_UPDATED":
        try:
            notification = OrderStatusUpdatedNotificationDTO(**raw_data)
            return await handle_order_status_updated(session, request, notification)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[Webhook] Error processing ORDER_STATUS_UPDATED: {e}")
            webhook_log.status = "error"
            webhook_log.error_message = str(e)
            await session.commit()
            raise HTTPException(status_code=500, detail=str(e))

    # Любой другой тип (отзывы, чаты и т.д.) — молча принимаем, чтобы не копить ошибки
    logger.info(f"[Webhook] Ignoring notification type: {notification_type}")
    return yandex_ok()


async def handle_order_created(
    session: AsyncSession,
    request: Request,
    notification: OrderCreatedNotificationDTO
) -> JSONResponse:
    order_id = str(notification.orderId)
    campaign_id = str(notification.campaignId)

    existing_order = await session.execute(
        select(Order).where(Order.order_id == order_id)
    )
    order = existing_order.scalar_one_or_none()

    if order and order.status == "DELIVERED":
        logger.info(f"[Webhook] Order {order_id} already delivered.")
        return yandex_ok()   # 🔥 валидное тело

    if order and order.status in ["PROCESSING", "RECEIVED"]:
        logger.info(f"[Webhook] Order {order_id} already in queue.")
        return yandex_ok()   # 🔥 валидное тело

    items_data = [item.model_dump() for item in notification.items]
    total_amount = 0.0
    currency = "RUB"
    created_at = datetime.now(timezone.utc)

    yandex_client = get_yandex_client()
    account = settings.accounts_by_campaign.get(campaign_id)

    if account:
        try:
            response = await yandex_client.get_orders2(
                business_id=account.business_id,
                order_ids=[int(order_id)],
                campaign_ids=[int(campaign_id)],
            )
            yandex_orders = response.get("result", {}).get("orders", [])
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
                logger.info(f"[Webhook] ✅ Got full order details: {order_id}")
            else:
                # Eventual consistency: данных ещё нет. 500 -> Яндекс повторит через ~мин.
                logger.warning(f"[Webhook] ⚠️ Order {order_id} not indexed yet. 500 -> Yandex retry.")
                raise ValueError("order not indexed yet")
        except ValueError:
            raise
        except Exception as e:
            logger.warning(f"[Webhook] ⚠️ Fetch failed for {order_id}: {e}. 500 -> Yandex retry.")
            raise HTTPException(status_code=500, detail=str(e))
    else:
        logger.error(f"[Webhook] ❌ Unknown campaign_id: {campaign_id}")
        raise HTTPException(status_code=500, detail="Unknown campaign")

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
        logger.info(f"[Webhook] ✅ Created order: {order_id}, Amount: {total_amount} {currency}")

    redis_pool = request.app.state.redis_pool
    job: Job = await redis_pool.enqueue_job('process_order_task', order_id, campaign_id)
    logger.info(f"[Webhook] 🚀 Enqueued fulfillment {order_id}, job={job.job_id}")

    return yandex_ok()   # 🔥 валидное тело вместо {"status":"accepted"}


async def handle_order_status_updated(
    session: AsyncSession,
    request: Request,
    notification: OrderStatusUpdatedNotificationDTO
) -> JSONResponse:
    order_id = str(notification.orderId)
    campaign_id = str(notification.campaignId)
    new_status = notification.status
    substatus = notification.substatus

    existing_order = await session.execute(
        select(Order).where(Order.order_id == order_id)
    )
    order = existing_order.scalar_one_or_none()

    if not order:
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
        return yandex_ok()   # 🔥 валидное тело

    if new_status == "PROCESSING" and substatus == "STARTED" and order.status != "PROCESSING":
        order.status = "PROCESSING"
        await session.commit()
        redis_pool = request.app.state.redis_pool
        await redis_pool.enqueue_job('process_order_task', order_id, campaign_id)
        logger.info(f"[Webhook] 🚀 Enqueued from status update: {order_id}")
        return yandex_ok()   # 🔥 валидное тело

    if new_status == "CANCELLED":
        order.status = "CANCELLED"
        await session.commit()
        logger.info(f"[Webhook] Order {order_id} cancelled")
        return yandex_ok()   # 🔥 валидное тело

    return yandex_ok()   # 🔥 валидное тело на любой другой статус
