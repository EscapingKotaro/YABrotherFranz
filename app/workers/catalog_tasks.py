# app/workers/catalog_tasks.py
import logging
from arq import ArqRedis

from app.database import async_session_factory
from app.services.catalog_sync import CatalogSyncService

logger = logging.getLogger(__name__)


async def sync_catalog_task(ctx: dict):
    """
    ARQ задача: синхронизация каталога для всех каналов.
    Запускается периодически (каждые 15 минут) или по событию.
    """
    logger.info("[CatalogWorker] Starting catalog sync task")
    
    async with async_session_factory() as session:
        sync_service = CatalogSyncService()
        
        # Инициализировать модуль (если ещё не инициализирован)
        init_result = await sync_service.initialize_module(session)
        
        if not init_result.get("success"):
            logger.error(f"[CatalogWorker] Initialization failed: {init_result}")
            return
        
        channels = init_result.get("channels", [])
        
        # Синхронизировать каждый канал
        for channel_id in channels:
            try:
                result = await sync_service.sync_channel(session, channel_id)
                logger.info(f"[CatalogWorker] Channel {channel_id}: {result}")
                
                # Обработать запросы на снятие
                removal_result = await sync_service.process_removal_requests(session, channel_id)
                logger.info(f"[CatalogWorker] Removal requests for {channel_id}: {removal_result}")
                
            except Exception as e:
                logger.error(f"[CatalogWorker] Error syncing channel {channel_id}: {e}")
                # Продолжаем с другими каналами
    
    logger.info("[CatalogWorker] ✅ Catalog sync task completed")


async def process_removal_requests_task(ctx: dict, channel_id: int):
    """ARQ задача: обработать запросы на снятие для конкретного канала"""
    logger.info(f"[CatalogWorker] Processing removal requests for channel {channel_id}")
    
    async with async_session_factory() as session:
        sync_service = CatalogSyncService()
        result = await sync_service.process_removal_requests(session, channel_id)
        logger.info(f"[CatalogWorker] ✅ Removal requests processed: {result}")