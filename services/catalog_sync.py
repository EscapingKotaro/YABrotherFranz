# app/services/catalog_sync.py
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import SyncState, CatalogItem, Listing
from app.services.clients.factory import get_cndk_client, get_yandex_client
from app.config import settings

logger = logging.getLogger(__name__)


class CatalogSyncService:
    """
    Сервис синхронизации каталога CNDK → Яндекс Маркет.
    
    Основной цикл:
    1. Получить каналы (GET /me)
    2. Заявить модуль (PUT /module-declaration)
    3. Читать слоты (GET /slots с long polling)
    4. Для каждого слота: создать/обновить/снять карточку в Яндексе
    5. Отчитаться (POST /listing-reports)
    """
    
    def __init__(self):
        self.cndk_client = get_cndk_client()
        self.yandex_client = get_yandex_client()
    
    async def initialize_module(self, session: AsyncSession) -> dict:
        """
        Инициализация модуля при старте:
        - Получить каналы
        - Заявить модуль (если ещё не заявлен)
        - Обновить состояние исполнителя
        """
        logger.info("[CatalogSync] Initializing module...")
        
        # 1. Получить каналы
        me_response = await self.cndk_client.get_me()
        channels = me_response.get("channels", [])
        
        if not channels:
            logger.warning("[CatalogSync] No channels available for this API key")
            return {"success": False, "error": "No channels"}
        
        logger.info(f"[CatalogSync] ✅ Found {len(channels)} channels")
        
        # 2. Заявить модуль (один раз на все каналы)
        declaration = {
            "declaration_revision": 1,  # Увеличивать при изменении
            "operations": [
                {
                    "name": "sync_slots",
                    "expected_interval_minutes": 15,
                }
            ],
            "reads_removal_requests": True,  # Держим карточки filtered_out/no_price/not_publishable
            "card_creating_operations": ["sync_slots"],
            "promotes_cards": False,
            "reuses_reserve_cards": False,
        }
        
        await self.cndk_client.declare_module(declaration)
        
        # 3. Обновить состояние исполнителя для каждого канала
        for channel in channels:
            channel_id = channel["id"]
            
            # Инициализировать SyncState если его нет
            sync_state = await session.execute(
                select(SyncState).where(SyncState.channel_id == channel_id)
            )
            state = sync_state.scalar_one_or_none()
            
            if not state:
                state = SyncState(channel_id=channel_id)
                session.add(state)
                await session.commit()
            
            # Обновить executor state
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
        """
        Один проход синхронизации для канала.
        Читает слоты, принимает решения, отправляет отчёты.
        """
        logger.info(f"[CatalogSync] Starting sync for channel {channel_id}")
        
        # Получить SyncState
        result = await session.execute(
            select(SyncState).where(SyncState.channel_id == channel_id)
        )
        sync_state = result.scalar_one_or_none()
        
        if not sync_state:
            logger.error(f"[CatalogSync] SyncState not found for channel {channel_id}")
            return {"success": False, "error": "SyncState not found"}
        
        cursor = sync_state.next_cursor
        
        # Читать слоты (long polling с wait=30)
        slots_response = await self.cndk_client.get_slots(
            channel_id=channel_id,
            cursor=cursor,
            wait=30,
            presentation=True,
        )
        
        slots = slots_response.get("slots", [])
        next_cursor = slots_response.get("next_cursor")
        
        logger.info(f"[CatalogSync] 📥 Got {len(slots)} slots from channel {channel_id}")
        
        # Обновить курсор
        sync_state.next_cursor = next_cursor
        sync_state.last_sync_at = datetime.utcnow()
        await session.commit()
        
        if not slots:
            logger.debug(f"[CatalogSync] No changes for channel {channel_id}")
            return {"success": True, "processed": 0}
        
        # Обработать каждый слот
        stats = {"created": 0, "updated": 0, "withdrawn": 0, "errors": 0}
        reports = []
        
        for slot in slots:
            try:
                report = await self._process_slot(session, channel_id, slot)
                if report:
                    reports.append(report)
                    
                    # Обновить статистику
                    if report["status"] == "published":
                        stats["created" if not report.get("_updated") else "updated"] += 1
                    elif report["status"] == "removed":
                        stats["withdrawn"] += 1
            except Exception as e:
                logger.error(f"[CatalogSync] Error processing slot {slot.get('id')}: {e}")
                stats["errors"] += 1
        
        # Отправить отчёты (батчем до 500)
        if reports:
            for i in range(0, len(reports), 500):
                batch = reports[i:i+500]
                await self.cndk_client.send_listing_reports(channel_id, batch)
        
        logger.info(f"[CatalogSync] ✅ Sync completed: {stats}")
        return {"success": True, **stats}
    
    async def _process_slot(self, session: AsyncSession, channel_id: int, slot: dict) -> Optional[dict]:
        """
        Обработка одного слота: создать/обновить/снять карточку.
        
        Логика по таблице из доки:
        - stale=true и withdraw=false → не создавать, не менять
        - withdraw=true → снять карточку
        - publish=false → не создавать, не менять
        - reason или presentation.reason не null → не создавать
        - publish=true → создать/обновить карточку
        """
        slot_id = slot["id"]
        publish = slot.get("publish", False)
        withdraw = slot.get("withdraw", False)
        stale = slot.get("stale", False)
        reason = slot.get("reason")
        presentation = slot.get("presentation") or {}
        presentation_reason = presentation.get("reason")
        
        # Найти существующее объявление для этого слота
        listings = slot.get("listings", [])
        existing_listing = None
        for listing in listings:
            if listing.get("status") not in ["removed"]:
                existing_listing = listing
                break
        
        # Найти локальную запись CatalogItem
        result = await session.execute(
            select(CatalogItem).where(
                CatalogItem.channel_id == channel_id,
                CatalogItem.channel_slot_id == slot_id,
            )
        )
        catalog_item = result.scalar_one_or_none()
        
        # Решить, что делать
        if stale and not withdraw:
            # Не создавать, не менять
            logger.debug(f"[CatalogSync] Slot {slot_id}: stale=true, skip")
            return None
        
        if withdraw:
            # Снять карточку
            if existing_listing:
                return await self._withdraw_listing(session, channel_id, slot, existing_listing)
            return None
        
        if not publish:
            # Не создавать, не менять
            logger.debug(f"[CatalogSync] Slot {slot_id}: publish=false, skip")
            return None
        
        if reason or presentation_reason:
            # Не создавать (слот неполный)
            logger.debug(f"[CatalogSync] Slot {slot_id}: reason={reason}, skip")
            return None
        
        # publish=true → создать или обновить карточку
        if existing_listing:
            # Обновить существующую
            return await self._update_listing(session, channel_id, slot, existing_listing)
        else:
            # Создать новую
            return await self._create_listing(session, channel_id, slot)
    
    async def _create_listing(self, session: AsyncSession, channel_id: int, slot: dict) -> dict:
        """Создать новую карточку в Яндексе"""
        slot_id = slot["id"]
        sellable_position_id = slot["sellable_position_id"]
        presentation = slot.get("presentation") or {}
        target = slot.get("target", {})
        
        # Сгенерировать external_id (offerId в Яндексе)
        # Формат: cndk-{sellable_position_id}-{channel_id}
        external_id = f"cndk-{sellable_position_id}-{channel_id}"
        
        logger.info(f"[CatalogSync] Creating listing {external_id} for slot {slot_id}")
        
        # TODO: Вызвать YandexClient.update_offer_mappings() для создания карточки
        # Пока просто логируем
        logger.info(f"[CatalogSync] 📦 Would create Yandex offer: {external_id}")
        logger.info(f"[CatalogSync] 💰 Price: {target.get('amount')} {target.get('currency')}")
        logger.info(f"[CatalogSync] 📝 Title: {presentation.get('title')}")
        
        # Обновить локальную тень CatalogItem
        catalog_item = CatalogItem(
            channel_id=channel_id,
            channel_slot_id=slot_id,
            sellable_position_id=sellable_position_id,
            product_name=slot.get("product_name"),
            product_variant_name=slot.get("product_variant_name"),
            product_type_identifier=slot.get("product_type_identifier"),
            axis_values=slot.get("axis_values"),
            publish=slot.get("publish"),
            withdraw=slot.get("withdraw"),
            intent_reason=slot.get("intent_reason"),
            stale=slot.get("stale"),
            target_amount=target.get("amount"),
            target_currency=target.get("currency"),
            presentation_title=presentation.get("title"),
            presentation_text=presentation.get("text"),
            presentation_gallery=presentation.get("gallery"),
        )
        session.add(catalog_item)
        await session.commit()
        
        # Создать отчёт
        report = {
            "report_id": f"{external_id}:{datetime.utcnow().isoformat()}",
            "external_id": external_id,
            "status": "published",
            "covered": [slot_id],
            "price_sellable_position_id": sellable_position_id,
            "reported_price": target,
            "presentation": {
                "title": presentation.get("title"),
                "text": presentation.get("text"),
                "images": [img["url"] for img in presentation.get("gallery", []) if img.get("url")],
                "lead_channel_slot_id": slot_id,
                "applied_set_version_id": presentation.get("effective_set_version_id"),
                "applied_block_versions": presentation.get("effective_block_versions", []),
            },
            "_updated": False,  # Внутренняя метка
        }
        
        # Создать локальную тень Listing
        listing = Listing(
            channel_id=channel_id,
            external_id=external_id,
            covered_channel_slot_ids=[slot_id],
            price_sellable_position_id=sellable_position_id,
            status="published",
            reported_price_amount=target.get("amount"),
            reported_price_currency=target.get("currency"),
            presentation_title=presentation.get("title"),
            presentation_text=presentation.get("text"),
            presentation_images=[img["url"] for img in presentation.get("gallery", []) if img.get("url")],
        )
        session.add(listing)
        await session.commit()
        
        return report
    
    async def _update_listing(self, session: AsyncSession, channel_id: int, slot: dict, existing_listing: dict) -> dict:
        """Обновить существующую карточку (цена, оформление)"""
        slot_id = slot["id"]
        external_id = existing_listing["external_id"]
        presentation = slot.get("presentation") or {}
        target = slot.get("target", {})
        
        logger.info(f"[CatalogSync] Updating listing {external_id} for slot {slot_id}")
        
        # TODO: Вызвать YandexClient.update_prices() и/или update_offer_mappings()
        logger.info(f"[CatalogSync] 💰 Would update price to: {target.get('amount')} {target.get('currency')}")
        
        # Обновить локальную тень
        result = await session.execute(
            select(Listing).where(Listing.external_id == external_id)
        )
        listing = result.scalar_one_or_none()
        
        if listing:
            listing.reported_price_amount = target.get("amount")
            listing.reported_price_currency = target.get("currency")
            listing.presentation_title = presentation.get("title")
            listing.presentation_text = presentation.get("text")
            await session.commit()
        
        # Создать отчёт
        report = {
            "report_id": f"{external_id}:{datetime.utcnow().isoformat()}",
            "external_id": external_id,
            "status": existing_listing.get("status", "published"),
            "covered": existing_listing.get("covered_channel_slot_ids", [slot_id]),
            "price_sellable_position_id": slot["sellable_position_id"],
            "reported_price": target,
            "presentation": {
                "title": presentation.get("title"),
                "text": presentation.get("text"),
                "images": [img["url"] for img in presentation.get("gallery", []) if img.get("url")],
                "lead_channel_slot_id": slot_id,
                "applied_set_version_id": presentation.get("effective_set_version_id"),
                "applied_block_versions": presentation.get("effective_block_versions", []),
            },
            "_updated": True,
        }
        
        return report
    
    async def _withdraw_listing(self, session: AsyncSession, channel_id: int, slot: dict, existing_listing: dict) -> dict:
        """Снять карточку с продажи"""
        slot_id = slot["id"]
        external_id = existing_listing["external_id"]
        
        logger.info(f"[CatalogSync] Withdrawing listing {external_id} for slot {slot_id}")
        
        # TODO: Вызвать YandexClient для снятия карточки (обнулить сток или удалить)
        logger.info(f"[CatalogSync] 🗑️ Would withdraw Yandex offer: {external_id}")
        
        # Обновить локальную тень
        result = await session.execute(
            select(Listing).where(Listing.external_id == external_id)
        )
        listing = result.scalar_one_or_none()
        
        if listing:
            listing.status = "removed"
            await session.commit()
        
        # Создать отчёт
        report = {
            "report_id": f"{external_id}:{datetime.utcnow().isoformat()}",
            "external_id": external_id,
            "status": "removed",
            "covered": existing_listing.get("covered_channel_slot_ids", [slot_id]),
        }
        
        return report
    
    async def process_removal_requests(self, session: AsyncSession, channel_id: int) -> dict:
        """Обработать запросы на снятие карточек от оператора CNDK"""
        logger.info(f"[CatalogSync] Processing removal requests for channel {channel_id}")
        
        # Получить объявления с запросом снятия
        listings_response = await self.cndk_client.get_listings(
            channel_id=channel_id,
            removal_requested=True,
        )
        
        listings = listings_response.get("listings", [])
        
        if not listings:
            logger.debug(f"[CatalogSync] No removal requests for channel {channel_id}")
            return {"success": True, "processed": 0}
        
        logger.info(f"[CatalogSync] 📥 Found {len(listings)} removal requests")
        
        reports = []
        for listing in listings:
            external_id = listing["external_id"]
            logger.info(f"[CatalogSync] 🗑️ Processing removal for {external_id}")
            
            # TODO: Снять карточку в Яндексе
            logger.info(f"[CatalogSync] Would withdraw {external_id}")
            
            # Создать отчёт со status=removed
            report = {
                "report_id": f"{external_id}:{datetime.utcnow().isoformat()}",
                "external_id": external_id,
                "status": "removed",
                "covered": listing.get("covered_channel_slot_ids", []),
            }
            reports.append(report)
            
            # Обновить локальную тень
            result = await session.execute(
                select(Listing).where(Listing.external_id == external_id)
            )
            local_listing = result.scalar_one_or_none()
            if local_listing:
                local_listing.status = "removed"
                local_listing.removal_requested_at = None
                await session.commit()
        
        # Отправить отчёты
        if reports:
            await self.cndk_client.send_listing_reports(channel_id, reports)
        
        logger.info(f"[CatalogSync] ✅ Processed {len(reports)} removal requests")
        return {"success": True, "processed": len(reports)}