# app/api/sync_api.py
from fastapi import APIRouter, HTTPException, Query
import logging
from typing import Optional

from app.config import settings
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