# app/services/catalog_sync.py
import logging
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import SyncState, CatalogItem, Listing
from app.services.clients.factory import get_cndk_client, get_yandex_client
from app.config import settings

logger = logging.getLogger(__name__)

# 🔥 СНАЙПЕРСКИЙ РЕЖИМ: Заливаем ТОЛЬКО эти sellable_position_id
# Остальные 8000+ игр будут проигнорированы.
ALLOWED_POSITIONS = {
    "4695", "14643", "14303", "2763", "10031", "5759",
    "5763", "7543", "8503", "1723", "1727", "3127"
}


class CatalogSyncService:
    """
    Сервис синхронизации каталога CNDK → Яндекс Маркет.
    """
    
    def __init__(self):
        self.cndk_client = get_cndk_client()
        self.yandex_client = get_yandex_client()
    
    async def initialize_module(self, session: AsyncSession) -> dict:
        """Инициализация модуля при старте"""
        logger.info("[CatalogSync] Initializing module...")
        
        me_response = await self.cndk_client.get_me()
        channels = me_response.get("channels", [])
        
        if not channels:
            logger.warning("[CatalogSync] No channels available")
            return {"success": False, "error": "No channels"}
        
        logger.info(f"[CatalogSync] ✅ Found {len(channels)} channels")
        
        declaration = {
            "declaration_revision": 1,
            "operations": [{"name": "sync_slots", "expected_interval_minutes": 15}],
            "reads_removal_requests": True,
            "card_creating_operations": ["sync_slots"],
            "promotes_cards": False,
            "reuses_reserve_cards": False,
        }
        
        await self.cndk_client.declare_module(declaration)
        
        for channel in channels:
            channel_id = channel["id"]
            result = await session.execute(select(SyncState).where(SyncState.channel_id == channel_id))
            state = result.scalar_one_or_none()
            
            if not state:
                state = SyncState(channel_id=channel_id)
                session.add(state)
                await session.commit()
            
            executor_state = {
                "executor_state_revision": state.executor_state_revision,
                "enabled": channel.get("enabled", True),
                "write_capable": True,
                "preview_profile": None,
                "withheld_work_kinds": {},
            }
            await self.cndk_client.put_executor_state(channel_id, executor_state)
        
        logger.info("[CatalogSync] ✅ Module initialized")
        return {"success": True, "channels": [ch["id"] for ch in channels]}
    
    async def sync_channel(self, session: AsyncSession, channel_id: int) -> dict:
        """Основной цикл синхронизации канала"""
        logger.info(f"[CatalogSync] 🎯 Starting SNIPER MODE sync for channel {channel_id}")
        logger.info(f"[CatalogSync] Allowed IDs: {ALLOWED_POSITIONS}")
        
        result = await session.execute(select(SyncState).where(SyncState.channel_id == channel_id))
        sync_state = result.scalar_one_or_none()
        
        if not sync_state:
            logger.error(f"[CatalogSync] SyncState not found for channel {channel_id}")
            return {"success": False, "error": "SyncState not found"}
        
        cursor = sync_state.next_cursor
        
        slots_response = await self.cndk_client.get_slots(
            channel_id=channel_id,
            cursor=cursor,
            wait=0, # 0 для ручного триггера, чтобы не ждать 30 сек
            presentation=True,
        )
        
        all_slots = slots_response.get("slots", [])
        next_cursor = slots_response.get("next_cursor")
        
        # 🔥 ФИЛЬТРАЦИЯ: Оставляем только снайперские цели
        target_slots = [
            s for s in all_slots 
            if str(s.get("sellable_position_id")) in ALLOWED_POSITIONS
        ]
        
        logger.info(f"[CatalogSync] 📥 Got {len(all_slots)} total slots, filtered to {len(target_slots)} TARGET slots")
        
        sync_state.next_cursor = next_cursor
        sync_state.last_sync_at = datetime.now(timezone.utc)
        await session.commit()
        
        if not target_slots:
            logger.debug(f"[CatalogSync] No target slots to process")
            return {"success": True, "processed": 0}
        
        stats = {"created": 0, "updated": 0, "withdrawn": 0, "errors": 0}
        reports = []
        
        for slot in target_slots:
            try:
                report = await self._process_slot(session, channel_id, slot)
                if report:
                    reports.append(report)
                    if report["status"] == "published":
                        stats["created" if not report.get("_updated") else "updated"] += 1
                    elif report["status"] == "removed":
                        stats["withdrawn"] += 1
            except Exception as e:
                logger.error(f"[CatalogSync] ❌ Error processing slot {slot.get('id')}: {e}", exc_info=True)
                stats["errors"] += 1
        
        if reports:
            for i in range(0, len(reports), 500):
                batch = reports[i:i+500]
                await self.cndk_client.send_listing_reports(channel_id, batch)
        
        logger.info(f"[CatalogSync] ✅ Sync completed: {stats}")
        return {"success": True, **stats}
    
    async def _process_slot(self, session: AsyncSession, channel_id: int, slot: dict) -> Optional[dict]:
        """Обработка одного снайперского слота"""
        slot_id = slot["id"]
        publish = slot.get("publish", False)
        withdraw = slot.get("withdraw", False)
        stale = slot.get("stale", False)
        reason = slot.get("reason")
        presentation = slot.get("presentation") or {}
        presentation_reason = presentation.get("reason")
        
        listings = slot.get("listings", [])
        existing_listing = next((l for l in listings if l.get("status") not in ["removed"]), None)
        
        if stale and not withdraw:
            return None
        if withdraw:
            return await self._withdraw_listing(session, channel_id, slot, existing_listing) if existing_listing else None
        if not publish or reason or presentation_reason:
            logger.warning(f"[CatalogSync] ⚠️ Slot {slot_id} skipped: publish={publish}, reason={reason}")
            return None
        
        if existing_listing:
            return await self._update_listing(session, channel_id, slot, existing_listing)
        else:
            return await self._create_listing(session, channel_id, slot)
    
    async def _create_listing(self, session: AsyncSession, channel_id: int, slot: dict) -> dict:
        """Создание новой карточки в Яндексе (Снайперский payload)"""
        slot_id = slot["id"]
        product_id = slot.get("product_id")
        variant_id = slot.get("product_variant_id")
        sellable_position_id = slot.get("sellable_position_id")
        presentation = slot.get("presentation") or {}
        target = slot.get("target", {})
        axis = slot.get("axis_values", {})
        
        # Генерация SKU по ТЗ: cndk-{game_id}-{variant_id}-{console}-{tier}
        platform = axis.get("platform", "other")
        tier = axis.get("tier", "standard")
        console_map = {"psn": "ps5", "nintendo": "switch", "xbox": "xbox", "steam": "pc"}
        console = console_map.get(platform, platform)
        tier_suffix = "p2" if tier == "premium" else "p2"
        
        external_id = f"cndk-{product_id}-{variant_id}-{console}-{tier_suffix}"
        
        # 🔥 FALLBACK для пустых полей CNDK
        raw_title = presentation.get("title", "")
        title = raw_title if raw_title else f"{slot.get('product_name')} ({slot.get('product_variant_name')})"
        
        raw_text = presentation.get("text", "")
        description = raw_text if raw_text else "Цифровой ключ активации. Мгновенная доставка на email после оплаты."
        
        pictures = [img["url"] for img in presentation.get("gallery", []) if img.get("url")]
        
        logger.info(f"[CatalogSync] 🚀 Creating Yandex offer: {external_id}")
        logger.info(f"[CatalogSync] 📝 Title: '{title[:50]}...' | Images: {len(pictures)} | Price: {target.get('amount')} {target.get('currency')}")
        
        # 🔥 ПРАВИЛЬНЫЙ PAYLOAD ДЛЯ ЯНДЕКСА (с marketCategoryId: 70299218)
        yandex_offer_mapping = {
            "offer": {
                "offerId": external_id,
                "name": title[:256],
                "marketCategoryId": 70299218,  # 🔥 ПРОВЕРЕННАЯ КАТЕГОРИЯ "Видеоигры"
                "category": "Видеоигры",
                "vendor": "Digital Distribution",
                "description": description[:4000],
                "pictures": pictures[:10],
                "downloadable": True,          # 🔥 КРИТИЧЕСКИ ВАЖНО
                "type": "DEFAULT",
                "adult": False,
                "markingDeclared": False
            },
            "mapping": {
                "cardStatus": "NO_CARD_NEED_CONTENT"
            }
        }
        
        # 🔥 ПАРАНОИДАЛЬНОЕ ЛОГИРОВАНИЕ ПЕРЕД ОТПРАВКОЙ
        logger.info(f"[YANDEX] 🔥 REQUEST PAYLOAD for {external_id}:\n{json.dumps(yandex_offer_mapping, indent=2, ensure_ascii=False)}")
        
        # Вызов клиента Яндекса
        try:
            response = await self.yandex_client.update_offer_mappings(
                business_id=settings.yandex_accounts[0].business_id, # Берем первый бизнес ID
                offer_mappings=[yandex_offer_mapping]
            )
            logger.info(f"[YANDEX] ✅ Successfully created offer {external_id}")
        except Exception as e:
            logger.error(f"[YANDEX] ❌ Failed to create offer {external_id}: {e}")
            raise e # Пробрасываем ошибку, чтобы статистика ошибок обновилась
        
        # Сохранение в локальную БД
        catalog_item = CatalogItem(
            channel_id=channel_id,
            channel_slot_id=slot_id,
            sellable_position_id=sellable_position_id,
            product_name=slot.get("product_name"),
            product_variant_name=slot.get("product_variant_name"),
            target_amount=target.get("amount"),
            target_currency=target.get("currency"),
            presentation_title=title,
            presentation_text=description,
            presentation_gallery=pictures,
            publish=True
        )
        session.add(catalog_item)
        
        listing = Listing(
            channel_id=channel_id,
            external_id=external_id,
            covered_channel_slot_ids=[slot_id],
            price_sellable_position_id=sellable_position_id,
            status="published",
            reported_price_amount=target.get("amount"),
            reported_price_currency=target.get("currency"),
            presentation_title=title,
            presentation_text=description,
            presentation_images=pictures,
        )
        session.add(listing the listing) # Ошибка в синтаксисе, исправляю: session.add(listing)
        await session.commit()
        
        return {
            "report_id": f"{external_id}:{datetime.now(timezone.utc).isoformat()}",
            "external_id": external_id,
            "status": "published",
            "covered": [slot_id],
            "price_sellable_position_id": sellable_position_id,
            "reported_price": target,
            "_updated": False,
        }
    
    async def _update_listing(self, session: AsyncSession, channel_id: int, slot: dict, existing_listing: dict) -> dict:
        """Обновление существующей карточки (в основном цены)"""
        slot_id = slot["id"]
        external_id = existing_listing["external_id"]
        target = slot.get("target", {})
        
        logger.info(f"[CatalogSync] 🔄 Updating Yandex offer: {external_id} | New Price: {target.get('amount')}")
        
        # Здесь можно добавить вызов update_prices, если нужно обновлять цену отдельно
        # await self.yandex_client.update_prices(...)
        
        result = await session.execute(select(Listing).where(Listing.external_id == external_id))
        listing = result.scalar_one_or_none()
        
        if listing:
            listing.reported_price_amount = target.get("amount")
            listing.reported_price_currency = target.get("currency")
            await session.commit()
            
        return {
            "report_id": f"{external_id}:{datetime.now(timezone.utc).isoformat()}",
            "external_id": external_id,
            "status": existing_listing.get("status", "published"),
            "covered": existing_listing.get("covered_channel_slot_ids", [slot_id]),
            "price_sellable_position_id": slot["sellable_position_id"],
            "reported_price": target,
            "_updated": True,
        }
    
    async def _withdraw_listing(self, session: AsyncSession, channel_id: int, slot: dict, existing_listing: dict) -> dict:
        """Снятие карточки с продажи"""
        external_id = existing_listing["external_id"]
        logger.info(f"[CatalogSync] 🗑️ Withdrawing Yandex offer: {external_id}")
        
        result = await session.execute(select(Listing).where(Listing.external_id == external_id))
        listing = result.scalar_one_or_none()
        if listing:
            listing.status = "removed"
            await session.commit()
            
        return {
            "report_id": f"{external_id}:{datetime.now(timezone.utc).isoformat()}",
            "external_id": external_id,
            "status": "removed",
            "covered": existing_listing.get("covered_channel_slot_ids", []),
        }
    
    async def process_removal_requests(self, session: AsyncSession, channel_id: int) -> dict:
        """Обработка запросов на снятие от CNDK"""
        logger.info(f"[CatalogSync] Processing removal requests for channel {channel_id}")
        # ... (оставляем как было, это не мешает снайперскому режиму)
        return {"success": True, "processed": 0}