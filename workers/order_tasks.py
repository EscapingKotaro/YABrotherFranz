# app/workers/order_tasks.py
import logging
from arq import ArqRedis

from app.database import async_session_factory
from app.services.fulfillment import FulfillmentService

logger = logging.getLogger(__name__)


async def process_order_task(ctx: dict, order_id: str, campaign_id: str):
    """
    ARQ задача: обработка заказа и выдача кода.
    Запускается при получении вебхука от Яндекса.
    """
    logger.info(f"[OrderWorker] Processing order {order_id} from campaign {campaign_id}")
    
    async with async_session_factory() as session:
        fulfillment_service = FulfillmentService()
        
        try:
            result = await fulfillment_service.deliver_order(
                session=session,
                order_id=order_id,
                campaign_id=campaign_id,
            )
            
            logger.info(f"[OrderWorker] ✅ Order {order_id} processed: {result}")
        
        except Exception as e:
            logger.error(f"[OrderWorker] ❌ Error processing order {order_id}: {e}")
            # TODO: Отправить в DLQ и алерт в Telegram
            raise