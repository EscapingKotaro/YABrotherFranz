# app/api/sync_api.py
from fastapi import APIRouter, HTTPException
import logging

from app.config import settings
from app.services.clients.factory import get_cndk_client

router = APIRouter(prefix="/api/sync", tags=["sync"])
logger = logging.getLogger(__name__)


@router.get("/cndk-slots")
async def get_cndk_slots(channel_id: int = 12):
    """
    Посмотреть, какие слоты сейчас отдает CNDK (для ручного выбора игр).
    """
    cndk_client = get_cndk_client()

    try:
        # Делаем запрос без long polling (wait=0), чтобы получить ответ сразу
        response = await cndk_client.get_slots(
            channel_id=channel_id,
            cursor=None,
            wait=0,
            presentation=True
        )
        return {
            "success": True,
            "channel_id": channel_id,
            "next_cursor": response.get("next_cursor"),
            "slots_count": len(response.get("slots", [])),
            "slots": response.get("slots", [])
        }
    except Exception as e:
        logger.error(f"[SyncAPI] Error fetching CNDK slots: {e}")
        raise HTTPException(status_code=500, detail=str(e))
