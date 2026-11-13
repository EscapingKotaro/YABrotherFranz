# app/api/webhooks.py
from fastapi import APIRouter, Request, HTTPException, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from arq.jobs import Job
import logging

from app.database import get_session
from app.config import settings
from app.schemas.yandex_webhook import OrderWebhookDTO
from app.services.yandex_webhook_validator import YandexWebhookValidator
from app.models.order import Order
from sqlalchemy import select
from app.models.webhook import WebhookLog

router = APIRouter(prefix="/webhook/yandex", tags=["webhooks"])
logger = logging.getLogger(__name__)


def _get_account_by_api_key(api_key: str):
    """Находим аккаунт по Api-Key из заголовка"""
    for account in settings.yandex_accounts:
        if account.api_key == api_key:
            return account
    return None


@router.post("/order/status")
async def receive_order_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """
    Прием вебхука от Яндекс Маркета о изменении статуса заказа.
    
    URL регистрируем в кабинете Яндекса: https://наш-домен/webhook/yandex/order/status
    campaign_id определяем по Api-Key в заголовке Authorization.
    """
    
    # 1. Получаем Api-Key из заголовка
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header"
        )
    
    api_key = auth_header.replace("Bearer ", "")
    account = _get_account_by_api_key(api_key)
    
    if not account:
        logger.error(f"[Webhook] Unknown API key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown API key"
        )
    
    campaign_id = account.campaign_id
    
    # 2. Читаем raw body и signature
    payload_bytes = await request.body()
    signature = request.headers.get("X-Yandex-Signature")
    
    # 3. Валидация подписи
    YandexWebhookValidator.validate(payload_bytes, signature, campaign_id)
    
    # 4. Парсим payload
    try:
        webhook_data = OrderWebhookDTO.model_validate_json(payload_bytes)
    except Exception as e:
        logger.error(f"[Webhook] Failed to parse payload: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")

    log_entry = WebhookLog(
    campaign_id=campaign_id,
    order_id=str(webhook_data.orderId),
    webhook_type="order_status",
    payload=webhook_data.model_dump(),
    signature_valid=True, # Если дошли сюда, значит валидна
    status="accepted"
)
    session.add(log_entry)
    await session.commit()
    
    # 5. Извлекаем order_id из payload
    order_id = str(webhook_data.orderId)
    
    # 6. Фильтруем только PROCESSING
    if webhook_data.orderStatus != "PROCESSING":
        logger.info(f"[Webhook] Ignoring order {order_id} with status {webhook_data.orderStatus}")
        return {"status": "ignored", "reason": "not_processing"}
    
    # 7. Проверка идемпотентности
    existing_order = await session.execute(
        select(Order).where(Order.order_id == order_id)
    )
    order = existing_order.scalar_one_or_none()
    
    if order and order.status == "DELIVERED":
        logger.info(f"[Webhook] Order {order_id} already delivered, skipping")
        return {"status": "ignored", "reason": "already_delivered"}
    
    # 8. Создаем запись о заказе
    if not order:
        order = Order(
            order_id=order_id,
            campaign_id=campaign_id,
            customer_id=webhook_data.buyer.id if webhook_data.buyer else None,
            status="RECEIVED",
            items_data=[item.model_dump() for item in webhook_data.items],
            total_amount=webhook_data.itemsTotal,
            currency=webhook_data.currency,
        )
        session.add(order)
        await session.commit()
        logger.info(f"[Webhook] Created order record: {order_id} for campaign {campaign_id}")
    
    # 9. Ставим задачу в ARQ очередь
    redis_pool = request.app.state.redis_pool
    job: Job = await redis_pool.enqueue_job(
        'process_order_task',
        order_id,
        campaign_id,
        _queue_name='fulfillment'
    )
    
    logger.info(f"[Webhook] Enqueued order {order_id} for processing, job_id={job.job_id}")
    
    # 10. Быстрый ответ Яндексу
    return {
        "status": "accepted",
        "order_id": order_id,
        "campaign_id": campaign_id,
        "job_id": job.job_id
    }


@router.get("/health")
async def health_check():
    """Healthcheck для Docker/K8s"""
    return {"status": "ok"}
