# app/api/sync_api.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
import logging
from typing import Optional

from app.database import get_session
from app.config import settings
from app.services.catalog_sync import CatalogSyncService
from app.services.clients.factory import get_cndk_client

router = APIRouter(prefix="/api/sync", tags=["sync"])
logger = logging.getLogger(__name__)


@router.get("/cndk-slots")
async def get_cndk_slots(
    channel_id: int = 15,  # 🔥 Реальный канал
    cursor: Optional[str] = Query(None, description="Курсор пагинации"),
    search: Optional[str] = Query(None, description="Поиск по названию"),
):
    """
    Посмотреть, какие слоты сейчас отдает CNDK (для ручного выбора игр).
    Поддерживает пагинацию через cursor и поиск по названию.
    """
    cndk_client = get_cndk_client()

    try:
        # 🔥 ПЕРЕДАЁМ cursor в клиент!
        response = await cndk_client.get_slots(
            channel_id=channel_id,
            cursor=cursor,  # 🔥 ВОТ ЭТО ИСПРАВЛЕНИЕ
            wait=0,
            presentation=True
        )
        
        slots = response.get("slots", [])
        
        # 🔥 Опциональная фильтрация по поисковому запросу
        if search:
            search_lower = search.lower()
            slots = [
                s for s in slots
                if search_lower in s.get("product_name", "").lower()
                or search_lower in s.get("product_variant_name", "").lower()
            ]
        
        return {
            "success": True,
            "channel_id": channel_id,
            "next_cursor": response.get("next_cursor"),
            "slots_count": len(slots),
            "search_query": search,
            "slots": slots
        }
    except Exception as e:
        logger.error(f"[SyncAPI] Error fetching CNDK slots: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/trigger")
async def trigger_sync(
    channel_id: int,
    session: AsyncSession = Depends(get_session)
):
    """Ручной запуск синхронизации конкретного канала CNDK -> Яндекс"""
    try:
        sync_service = CatalogSyncService()
        
        # 1. Инициализация (если нужно)
        await sync_service.initialize_module(session)
        
        # 2. Синхронизация (Снайперский режим внутри)
        result = await sync_service.sync_channel(session, channel_id)
        
        # 3. Обработка запросов на снятие
        removal_result = await sync_service.process_removal_requests(session, channel_id)
        
        return {
            "success": True,
            "channel_id": channel_id,
            "sync_result": result,
            "removal_result": removal_result
        }
    except Exception as e:
        logger.error(f"[SyncAPI] Error triggering sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))