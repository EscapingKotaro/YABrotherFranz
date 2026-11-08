# app/services/clients/cndk_client.py
import logging
import asyncio
from typing import Optional

import httpx

from app.config import settings
from app.core.retry import retry_with_backoff

logger = logging.getLogger(__name__)


class RealCndkClient:
    """
    Клиент для CNDK Posting API v1.
    Работает с песочницей или продом в зависимости от конфига.
    """
    
    def __init__(self):
        self.base_url = settings.cndk_api_url.rstrip("/")
        self.api_key = settings.cndk_api_key
        
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(60.0, connect=10.0),  # Long polling требует больше времени
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
    
    # ============================================================
    # МОДУЛЬ И КАНАЛЫ
    # ============================================================
    
    @retry_with_backoff(max_retries=3, base_delay=2)
    async def get_me(self) -> dict:
        """Получить область доступа ключа и список каналов"""
        logger.debug("[CNDK] GET /api/v1/me")
        response = await self.client.get("/api/v1/me")
        response.raise_for_status()
        result = response.json()
        logger.info(f"[CNDK] ✅ Got {len(result.get('channels', []))} channels")
        return result
    
    @retry_with_backoff(max_retries=3, base_delay=2)
    async def declare_module(self, declaration: dict) -> dict:
        """Заявить модуль (операции, поля карточек, reads_removal_requests)"""
        logger.info(f"[CNDK] PUT /api/v1/module-declaration | revision={declaration.get('declaration_revision')}")
        response = await self.client.put("/api/v1/module-declaration", json=declaration)
        response.raise_for_status()
        result = response.json()
        logger.info("[CNDK] ✅ Module declared")
        return result
    
    # ============================================================
    # СЛОТЫ (основной цикл синхронизации)
    # ============================================================
    
    @retry_with_backoff(max_retries=3, base_delay=2)
    async def get_slots(
        self,
        channel_id: int,
        cursor: Optional[str] = None,
        wait: int = 30,
        presentation: bool = True,
    ) -> dict:
        """
        Получить изменённые слоты канала.
        
        Args:
            channel_id: ID канала
            cursor: Курсор из предыдущего ответа (None для первого запроса)
            wait: Сколько секунд ждать изменений (0-30)
            presentation: Включить оформление слотов
        
        Returns:
            {"slots": [...], "next_cursor": "..."}
        """
        params = {"wait": wait, "presentation": str(presentation).lower()}
        if cursor:
            params["cursor"] = cursor
        
        logger.debug(f"[CNDK] GET /api/v1/channels/{channel_id}/slots | cursor={cursor}, wait={wait}")
        
        response = await self.client.get(
            f"/api/v1/channels/{channel_id}/slots",
            params=params,
        )
        response.raise_for_status()
        
        result = response.json()
        slots_count = len(result.get("slots", []))
        logger.info(f"[CNDK] 📥 Got {slots_count} slots from channel {channel_id}")
        return result
    
    @retry_with_backoff(max_retries=3, base_delay=2)
    async def read_slot_presentations(
        self,
        channel_id: int,
        channel_slot_ids: list[int],
    ) -> list[dict]:
        """Прочитать оформление выбранных слотов (до 200 за раз)"""
        logger.debug(f"[CNDK] POST /api/v1/channels/{channel_id}/slot-presentations/read | slots={len(channel_slot_ids)}")
        response = await self.client.post(
            f"/api/v1/channels/{channel_id}/slot-presentations/read",
            json={"channel_slot_ids": channel_slot_ids},
        )
        response.raise_for_status()
        return response.json()
    
    # ============================================================
    # ОБЪЯВЛЕНИЯ (отчёты и чтение)
    # ============================================================
    
    @retry_with_backoff(max_retries=3, base_delay=2)
    async def send_listing_reports(
        self,
        channel_id: int,
        reports: list[dict],
    ) -> list[dict]:
        """
        Отправить отчёты об объявлениях (до 500 за раз).
        
        Args:
            channel_id: ID канала
            reports: Список отчётов с report_id, external_id, status, covered, presentation и т.д.
        
        Returns:
            Список ответов в том же порядке
        """
        logger.info(f"[CNDK] POST /api/v1/channels/{channel_id}/listing-reports | reports={len(reports)}")
        response = await self.client.post(
            f"/api/v1/channels/{channel_id}/listing-reports",
            json={"reports": reports},
        )
        response.raise_for_status()
        result = response.json()
        logger.info(f"[CNDK] ✅ Reports sent")
        return result
    
    @retry_with_backoff(max_retries=3, base_delay=2)
    async def get_listings(
        self,
        channel_id: int,
        cursor: Optional[str] = None,
        limit: int = 500,
        removal_requested: Optional[bool] = None,
        presentation: bool = True,
    ) -> dict:
        """
        Получить список объявлений канала.
        
        Args:
            removal_requested: True — только с запросом снятия, False — только без, None — все
        """
        params = {"limit": min(limit, 500), "presentation": str(presentation).lower()}
        if cursor:
            params["cursor"] = cursor
        if removal_requested is not None:
            params["removal_requested"] = str(removal_requested).lower()
        
        logger.debug(f"[CNDK] GET /api/v1/channels/{channel_id}/listings | removal_requested={removal_requested}")
        
        response = await self.client.get(
            f"/api/v1/channels/{channel_id}/listings",
            params=params,
        )
        response.raise_for_status()
        
        result = response.json()
        listings_count = len(result.get("listings", []))
        logger.info(f"[CNDK] 📥 Got {listings_count} listings")
        return result
    
    # ============================================================
    # ПОЗИЦИИ (поиск для привязки существующих карточек)
    # ============================================================
    
    @retry_with_backoff(max_retries=3, base_delay=2)
    async def search_positions(
        self,
        channel_id: int,
        name: str,
        platform: Optional[str] = None,
        console: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> list[dict]:
        """
        Найти позиции канала по названию игры.
        Используется для привязки существующих карточек кабинета.
        """
        payload = {"name": name}
        if platform:
            payload["platform"] = platform
        if console:
            payload["console"] = console
        if tier:
            payload["tier"] = tier
        
        logger.debug(f"[CNDK] POST /api/v1/channels/{channel_id}/positions/search | name={name}")
        
        response = await self.client.post(
            f"/api/v1/channels/{channel_id}/positions/search",
            json=payload,
        )
        response.raise_for_status()
        return response.json()
    
    # ============================================================
    # СОСТОЯНИЕ ИСПОЛНИТЕЛЯ
    # ============================================================
    
    @retry_with_backoff(max_retries=3, base_delay=2)
    async def put_executor_state(self, channel_id: int, state: dict) -> dict:
        """Записать состояние исполнителя (enabled, write_capable)"""
        logger.info(f"[CNDK] PUT /api/v1/channels/{channel_id}/executor-state")
        response = await self.client.put(
            f"/api/v1/channels/{channel_id}/executor-state",
            json=state,
        )
        response.raise_for_status()
        return response.json()
    
    @retry_with_backoff(max_retries=3, base_delay=2)
    async def get_executor_state(self, channel_id: int) -> dict:
        """Прочитать состояние исполнителя"""
        logger.debug(f"[CNDK] GET /api/v1/channels/{channel_id}/executor-state")
        response = await self.client.get(f"/api/v1/channels/{channel_id}/executor-state")
        response.raise_for_status()
        return response.json()
    
    async def close(self):
        await self.client.aclose()


class MockCndkClient:
    """
    Мок-клиент для CNDK Posting API v1.
    Эмулирует поведение Core: выдаёт тестовые слоты, принимает отчёты.
    """
    
    def __init__(self):
        self._cursor_counter = 0
        self._listings = {}  # external_id -> listing
        self._mock_channels = [
            {
                "id": 12,
                "name": "Yandex MSK Digital",
                "enabled": True,
                "marketplace_identifier": "yandex",
                "currency": "RUB",
            }
        ]
    
    async def get_me(self) -> dict:
        logger.info("[MOCK_CNDK] GET /api/v1/me")
        logger.info(f"[MOCK_CNDK] ✅ Returning {len(self._mock_channels)} channels")
        return {
            "module_identifier": "yandex_market_client",
            "marketplace_identifier": "yandex",
            "channel_ids": [ch["id"] for ch in self._mock_channels],
            "actions": ["read_positions", "write_listings", "declare_module"],
            "channels": self._mock_channels,
            "module_declaration_revision": 1,
        }
    
    async def declare_module(self, declaration: dict) -> dict:
        logger.info(f"[MOCK_CNDK] PUT /api/v1/module-declaration | revision={declaration.get('declaration_revision')}")
        logger.info(f"[MOCK_CNDK] ✅ Module declared with operations: {declaration.get('operations', [])}")
        return declaration
    
    async def get_slots(
        self,
        channel_id: int,
        cursor: Optional[str] = None,
        wait: int = 30,
        presentation: bool = True,
    ) -> dict:
        logger.info(f"[MOCK_CNDK] GET /api/v1/channels/{channel_id}/slots | cursor={cursor}, wait={wait}")
        
        # Эмулируем long polling: если курсор есть — возвращаем пустую страницу
        if cursor:
            logger.info("[MOCK_CNDK] ⏳ No changes, returning empty page")
            return {"slots": [], "next_cursor": f"mock_cursor_{self._cursor_counter}"}
        
        # Первый запрос — возвращаем тестовые слоты
        self._cursor_counter += 1
        mock_slots = [
            {
                "id": 3302,
                "sellable_position_id": 846,
                "publish": True,
                "withdraw": False,
                "intent_reason": None,
                "reason": None,
                "stale": False,
                "product_name": "The Witcher 3: Wild Hunt",
                "product_variant_name": "Complete Edition",
                "product_type_identifier": "game",
                "axis_values": {
                    "platform": "psn",
                    "price_group": "ps",
                    "tier": "premium",
                    "delivery_type": "edbs",
                },
                "release_date": "2015-05-19",
                "target": {"amount": "1990.00", "currency": "RUB"},
                "presentation": {
                    "title": "Ведьмак 3: Дикая Охота. Полное издание PS5",
                    "text": "Ролевая игра в открытом мире. Игру активируем на ваш аккаунт PSN после оплаты.",
                    "gallery": [
                        {"status": "ready", "url": "https://mock.url/witcher3-cover.jpg"},
                    ],
                    "effective_set_version_id": 41,
                    "effective_block_versions": [{"kind": "about", "key": "", "id": 905}],
                    "reason": None,
                } if presentation else None,
                "listings": [],
            },
            {
                "id": 3303,
                "sellable_position_id": 847,
                "publish": True,
                "withdraw": False,
                "intent_reason": None,
                "reason": None,
                "stale": False,
                "product_name": "EA SPORTS FC 26",
                "product_variant_name": "Standard Edition",
                "product_type_identifier": "game",
                "axis_values": {
                    "platform": "psn",
                    "price_group": "ps",
                    "tier": "standard",
                    "delivery_type": "edbs",
                },
                "release_date": "2025-09-26",
                "target": {"amount": "2490.00", "currency": "RUB"},
                "presentation": {
                    "title": "EA SPORTS FC 26 Standard PS5",
                    "text": "Футбольный симулятор. Активация на аккаунт PSN.",
                    "gallery": [
                        {"status": "ready", "url": "https://mock.url/fc26-cover.jpg"},
                    ],
                    "effective_set_version_id": 41,
                    "effective_block_versions": [],
                    "reason": None,
                } if presentation else None,
                "listings": [],
            },
        ]
        
        logger.info(f"[MOCK_CNDK] ✅ Returning {len(mock_slots)} test slots")
        return {"slots": mock_slots, "next_cursor": f"mock_cursor_{self._cursor_counter}"}
    
    async def read_slot_presentations(self, channel_id: int, channel_slot_ids: list[int]) -> list[dict]:
        logger.info(f"[MOCK_CNDK] POST /api/v1/channels/{channel_id}/slot-presentations/read | slots={channel_slot_ids}")
        return []
    
    async def send_listing_reports(self, channel_id: int, reports: list[dict]) -> list[dict]:
        logger.info(f"[MOCK_CNDK] POST /api/v1/channels/{channel_id}/listing-reports | reports={len(reports)}")
        
        results = []
        for report in reports:
            external_id = report.get("external_id")
            self._listings[external_id] = report
            logger.info(f"[MOCK_CNDK] 📝 Listing {external_id}: status={report.get('status')}, covered={report.get('covered')}")
            
            results.append({
                "id": 6418 + len(results),
                "channel_id": channel_id,
                "external_id": external_id,
                "status": report.get("status"),
                "covered_channel_slot_ids": report.get("covered", []),
                "report_outdated": False,
            })
        
        logger.info(f"[MOCK_CNDK] ✅ All {len(reports)} reports accepted")
        return results
    
    async def get_listings(
        self,
        channel_id: int,
        cursor: Optional[str] = None,
        limit: int = 500,
        removal_requested: Optional[bool] = None,
        presentation: bool = True,
    ) -> dict:
        logger.info(f"[MOCK_CNDK] GET /api/v1/channels/{channel_id}/listings | removal_requested={removal_requested}")
        
        listings = list(self._listings.values())
        if removal_requested is True:
            listings = []  # В моке нет removal requests
        elif removal_requested is False:
            pass  # Все listings
        
        logger.info(f"[MOCK_CNDK] ✅ Returning {len(listings)} listings")
        return {"listings": listings, "next_cursor": None}
    
    async def search_positions(
        self,
        channel_id: int,
        name: str,
        platform: Optional[str] = None,
        console: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> list[dict]:
        logger.info(f"[MOCK_CNDK] POST /api/v1/channels/{channel_id}/positions/search | name={name}")
        return []
    
    async def put_executor_state(self, channel_id: int, state: dict) -> dict:
        logger.info(f"[MOCK_CNDK] PUT /api/v1/channels/{channel_id}/executor-state | enabled={state.get('enabled')}")
        logger.info("[MOCK_CNDK] ✅ Executor state updated")
        return state
    
    async def get_executor_state(self, channel_id: int) -> dict:
        logger.info(f"[MOCK_CNDK] GET /api/v1/channels/{channel_id}/executor-state")
        return {
            "executor_state_revision": 1,
            "enabled": True,
            "write_capable": True,
            "preview_profile": None,
            "withheld_work_kinds": {},
        }
    
    async def close(self):
        logger.info("[MOCK_CNDK] Client closed")