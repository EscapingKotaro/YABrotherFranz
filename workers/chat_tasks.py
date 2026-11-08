# app/workers/chat_tasks.py
import logging
from arq import ArqRedis

from app.database import async_session_factory
from app.services.chat_bridge import ChatBridgeService
from app.config import settings

logger = logging.getLogger(__name__)


async def poll_crm_tasks(ctx: dict):
    """
    ARQ задача: опрос CRM на наличие задач для отправки в Яндекс.
    Запускается каждые 5 секунд.
    """
    logger.debug("[ChatWorker] Polling CRM for pending tasks")
    
    async with async_session_factory() as session:
        chat_bridge = ChatBridgeService()
        
        # Опросить каждый marketplace
        for account in settings.yandex_accounts:
            try:
                result = await chat_bridge.process_outgoing_messages(
                    session=session,
                    crm_marketplace_name=account.crm_marketplace_name,
                )
                
                if result.get("processed", 0) > 0:
                    logger.info(f"[ChatWorker] {account.crm_marketplace_name}: {result}")
            
            except Exception as e:
                logger.error(f"[ChatWorker] Error processing {account.crm_marketplace_name}: {e}")
    
    logger.debug("[ChatWorker] ✅ CRM polling completed")