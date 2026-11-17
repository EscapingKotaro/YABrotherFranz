# app/services/clients/yandex_client.py
import logging
from typing import Optional
from datetime import datetime, timedelta

import httpx

from app.config import settings, YandexAccountConfig
from app.core.retry import retry_with_backoff

logger = logging.getLogger(__name__)


class RealYandexClient:
    """
    Реальный клиент для работы с API Яндекс Маркета.
    
    Поддерживает мульти-аккаунтность: api_key берётся из конфига
    по campaign_id для каждого запроса.
    """
    
    BASE_URL = "https://api.partner.market.yandex.ru"
    
    def __init__(self):
        # Общий HTTP-клиент с пулингом соединений и HTTP/2
        self.client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            http2=True,
            headers={
                "User-Agent": "YandexMarketClient/1.0 (Python/httpx)",
                "Content-Type": "application/json",
            }
        )
    
    def _get_account(self, campaign_id: str) -> YandexAccountConfig:
        """Получение конфига аккаунта по campaign_id"""
        account = settings.accounts_by_campaign.get(campaign_id)
        if not account:
            raise ValueError(f"Unknown campaign_id: {campaign_id}")
        return account
    
    def _get_headers(self, account: YandexAccountConfig) -> dict:
        """Формирование заголовков с нужным api_key"""
        return {
            "Api-Key": f"{account.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    
    # ============================================================
    # ЗАКАЗЫ (Fulfillment)
    # ============================================================
    
    @retry_with_backoff(max_retries=5, base_delay=2)
    async def deliver_digital_goods(
        self,
        campaign_id: str,
        order_id: str,
        items: list[dict],
    ) -> dict:
        """
        Передача цифровых кодов покупателю.
        
        Args:
            campaign_id: ID кампании Яндекса
            order_id: ID заказа
            items: Список товаров с кодами:
                [
                    {
                        "id": 1,  # ID товара в заказе (integer!)
                        "codes": ["ABCD-1234"],
                        "slip": "<p>Инструкция...</p>",
                        "activate_till": "2026-12-31"
                    }
                ]
        
        Returns:
            {"status": "OK"} при успехе
        
        Raises:
            httpx.HTTPStatusError: при ошибке API
        """
        account = self._get_account(campaign_id)
        url = f"/v2/campaigns/{campaign_id}/orders/{order_id}/deliverDigitalGoods"
        
        payload = {"items": items}
        
        logger.info(f"[YANDEX] POST {url} | items_count={len(items)}")
        logger.debug(f"[YANDEX] Payload: {payload}")
        
        response = await self.client.post(
            url,
            json=payload,
            headers=self._get_headers(account),
        )
        response.raise_for_status()
        
        result = response.json()
        logger.info(f"[YANDEX] ✅ Order {order_id} delivered: {result}")
        return result


    @retry_with_backoff(max_retries=3, base_delay=2)
    async def get_orders2(
        self,
        business_id: str,
        order_ids: list,  # Принимаем список, элементы могут быть str или int
        campaign_ids: list = None,
    ) -> dict:
        account = next((acc for acc in settings.yandex_accounts if str(acc.business_id) == str(business_id)), None)
        if not account:
            raise ValueError(f"Unknown business_id: {business_id}")

        url = f"/v1/businesses/{business_id}/orders"
        
        # 🔥 КРИТИЧЕСКИ ВАЖНО: Жесткое преобразование в int. Яндекс требует integer[], а не string[]!
        body = {
            "orderIds": [int(oid) for oid in order_ids],
            "fake": True
        }
        if campaign_ids:
            body["campaignIds"] = [int(cid) for cid in campaign_ids]

        # 🔥 ЛОГ ДЛЯ ОТЛАДКИ: Мы точно увидим, какой JSON улетает в Яндекс
        logger.info(f"[YANDEX] POST {url} | body={body}")

        response = await self.client.post(
            url,
            json=body,
            headers=self._get_headers(account),
        )
        
        # Если Яндекс вернет 400 Bad Request из-за типов, httpx сразу выбросит ошибку здесь
        response.raise_for_status()
        
        result = response.json()
        orders = result.get("result", {}).get("orders", [])
        
        # 🔥 ЛОГ ДЛЯ ОТЛАДКИ: Выведем ID заказов, которые реально вернул Яндекс
        returned_ids = [str(o.get("orderId")) for o in orders]
        logger.info(f"[YANDEX] 📥 Got {len(orders)} detailed orders. Returned IDs: {returned_ids}")
        
        return result
    
    @retry_with_backoff(max_retries=3, base_delay=2)
    async def get_orders(
        self,
        business_id: str,
        campaign_ids: list,  # Принимаем list, элементы могут быть str или int из FastAPI
        statuses: Optional[list[str]] = None,
        limit: int = 50,
        page_token: Optional[str] = None,
    ) -> dict:
        """
        Получение списка заказов (используется для кнопок на дашборде).
        
        Args:
            business_id: ID бизнеса
            campaign_ids: Список ID кампаний (до 50)
            statuses: Фильтр по статусам (PROCESSING, DELIVERED и т.д.)
            limit: Количество заказов на странице (макс 50)
            page_token: Токен пагинации
        
        Returns:
            {"result": {"orders": [...], "paging": {"nextPageToken": "..."}}}
        """
        # 1. Надежный поиск аккаунта: сначала по business_id, если не вышло - по первому campaign_id
        account = next((acc for acc in settings.yandex_accounts if str(acc.business_id) == str(business_id)), None)
        if not account and campaign_ids:
            account = next((acc for acc in settings.yandex_accounts if str(acc.campaign_id) == str(campaign_ids[0])), None)
            
        if not account:
            raise ValueError(f"Unknown business_id: {business_id} or campaign_id: {campaign_ids[0] if campaign_ids else 'None'}")
        
        url = f"/v1/businesses/{business_id}/orders"
        
        # 2. Query параметры
        params = {"limit": min(limit, 50)}
        if page_token:
            params["pageToken"] = page_token
        
        # 3. Body запроса: ЖЕСТКАЯ типизация в int + fake: True
        payload = {
            "campaignIds": [int(cid) for cid in campaign_ids],
            "fake": True  # 🔥 КРИТИЧЕСКИ ВАЖНО, чтобы дашборд видел тестовые заказы
        }
        
        if statuses:
            payload["statuses"] = statuses
        
        # 4. Информативное логирование (мы точно увидим, что улетело в Яндекс)
        logger.info(f"[YANDEX] POST {url} | payload={payload}, params={params}")
        
        # 5. Выполнение запроса
        response = await self.client.post(
            url,
            params=params,
            json=payload,
            headers=self._get_headers(account),
        )
        response.raise_for_status()
        
        # 6. Обработка и логирование ответа
        result = response.json()
        orders = result.get("result", {}).get("orders", [])
        orders_count = len(orders)
        logger.info(f"result {result}")
        
        
        # Выводим ID полученных заказов, чтобы сразу видеть, сработал ли фильтр
        returned_ids = [str(o.get("orderId")) for o in orders]
        logger.info(f"[YANDEX] 📥 Got {orders_count} orders from business {business_id}. IDs: {returned_ids}")
        
        return result
    
    # ============================================================
    # ЧАТЫ (Chat Bridge)
    # ============================================================
    
    @retry_with_backoff(max_retries=3, base_delay=1)
    async def send_chat_message(
        self,
        business_id: str,
        chat_id: str,
        message_text: str,
    ) -> dict:
        """
        Отправка сообщения в чат Яндекс Маркета.
        
        Args:
            business_id: ID бизнеса
            chat_id: ID чата в Яндексе
            message_text: Текст сообщения
        
        Returns:
            {"status": "OK"} при успехе
        """
        # Для чатов нам нужен campaign_id, чтобы получить api_key
        # Ищем аккаунт по business_id
        account = None
        for acc in settings.yandex_accounts:
            if acc.business_id == business_id:
                account = acc
                break
        
        if not account:
            raise ValueError(f"Unknown business_id: {business_id}")
        
        url = f"/v2/businesses/{business_id}/chats/message"
        params = {"chatId": chat_id}
        payload = {"message": message_text}
        
        logger.info(f"[YANDEX] POST {url} | chat_id={chat_id}")
        logger.debug(f"[YANDEX] Message: {message_text[:100]}...")
        
        response = await self.client.post(
            url,
            params=params,
            json=payload,
            headers=self._get_headers(account),
        )
        response.raise_for_status()
        
        result = response.json()
        logger.info(f"[YANDEX] ✅ Message sent to chat {chat_id}")
        return {"success": True, "response": result}
    
    @retry_with_backoff(max_retries=3, base_delay=1)
    async def get_chats(
        self,
        business_id: str,
        limit: int = 20,
        filters: Optional[dict] = None,
    ) -> dict:
        """
        Получение списка чатов.
        
        Args:
            business_id: ID бизнеса
            limit: Количество чатов на странице (макс 20)
            filters: Фильтры (например, {"types": ["CHAT"]})
        
        Returns:
            {"result": {"chats": [...], "paging": {...}}}
        """
        account = None
        for acc in settings.yandex_accounts:
            if acc.business_id == business_id:
                account = acc
                break
        
        if not account:
            raise ValueError(f"Unknown business_id: {business_id}")
        
        url = f"/v2/businesses/{business_id}/chats"
        params = {"limit": min(limit, 20)}
        payload = filters or {}
        
        logger.debug(f"[YANDEX] POST {url} | filters={filters}")
        
        response = await self.client.post(
            url,
            params=params,
            json=payload if payload else None,
            headers=self._get_headers(account),
        )
        response.raise_for_status()
        
        result = response.json()
        chats_count = len(result.get("result", {}).get("chats", []))
        logger.info(f"[YANDEX] 📥 Got {chats_count} chats from business {business_id}")
        return result
    
    # ============================================================
    # КАТАЛОГ (Автопостинг)
    # ============================================================
    
    @retry_with_backoff(max_retries=3, base_delay=2)
    async def update_offer_mappings(
        self,
        business_id: str,
        offer_mappings: list[dict],
    ) -> dict:
        """
        Добавление/обновление товаров в каталог Яндекс Маркета.
        
        Args:
            business_id: ID бизнеса
            offer_mappings: Список товаров (до 500 за раз):
                [
                    {
                        "offer": {
                            "offerId": "cndk-xxx-ps5-p2",
                            "name": "Игра для PS5",
                            "categoryIds": [90766],
                            "pictures": ["https://..."],
                            "vendor": "CD PROJEKT RED",
                            "description": "...",
                            "manufacturer": "...",
                            "weightDimensions": {...},
                            "shelfLife": "...",
                            "lifeTime": "...",
                            "customsCommodityCode": "...",
                            "certificates": ["..."],
                        },
                        "mapping": {
                            "marketCategoryId": 90766,
                            "parameters": [...]
                        },
                        "prices": {
                            "price": {"value": 1990, "currencyId": "RUB"},
                            "discountedPrice": "...",
                        },
                        "stocks": {"count": 100, "shopSKU": "..."}
                    }
                ]
        
        Returns:
            {"result": {"offerIds": [...]}}
        """
        account = None
        for acc in settings.yandex_accounts:
            if acc.business_id == business_id:
                account = acc
                break
        
        if not account:
            raise ValueError(f"Unknown business_id: {business_id}")
        
        url = f"/v2/businesses/{business_id}/offer-mappings/update"
        payload = {"offerMappings": offer_mappings}
        
        logger.info(f"[YANDEX] POST {url} | offers_count={len(offer_mappings)}")
        
        response = await self.client.post(
            url,
            json=payload,
            headers=self._get_headers(account),
        )
        response.raise_for_status()
        
        result = response.json()
        logger.info(f"[YANDEX] ✅ Offer mappings updated: {result}")
        return result
    
    @retry_with_backoff(max_retries=3, base_delay=2)
    async def update_prices(
        self,
        campaign_id: str,
        prices: list[dict],
    ) -> dict:
        """
        Обновление цен товаров.
        
        Args:
            campaign_id: ID кампании
            prices: Список цен:
                [
                    {
                        "offerId": "cndk-xxx-ps5-p2",
                        "price": {"value": 1990, "currencyId": "RUB"}
                    }
                ]
        
        Returns:
            {"result": {"offers": [...]}}
        """
        account = self._get_account(campaign_id)
        
        url = f"/v2/campaigns/{campaign_id}/offer-prices/updates"
        payload = {"offers": prices}
        
        logger.info(f"[YANDEX] POST {url} | prices_count={len(prices)}")
        
        response = await self.client.post(
            url,
            json=payload,
            headers=self._get_headers(account),
        )
        response.raise_for_status()
        
        result = response.json()
        logger.info(f"[YANDEX] ✅ Prices updated")
        return result
    
    @retry_with_backoff(max_retries=3, base_delay=2)
    async def update_stocks(
        self,
        campaign_id: str,
        stocks: list[dict],
    ) -> dict:
        """
        Обновление остатков товаров.
        
        Args:
            campaign_id: ID кампании
            stocks: Список остатков:
                [
                    {
                        "sku": "cndk-xxx-ps5-p2",
                        "warehouseId": 12345,
                        "items": [{"count": 100, "updatedAt": "..."}]
                    }
                ]
        
        Returns:
            {"result": {"warehouses": [...]}}
        """
        account = self._get_account(campaign_id)
        
        url = f"/campaigns/{campaign_id}/offers/stocks"
        payload = {"skus": stocks}
        
        logger.info(f"[YANDEX] PUT {url} | stocks_count={len(stocks)}")
        
        response = await self.client.put(
            url,
            json=payload,
            headers=self._get_headers(account),
        )
        response.raise_for_status()
        
        result = response.json()
        logger.info(f"[YANDEX] ✅ Stocks updated")
        return result

    @retry_with_backoff(max_retries=3, base_delay=2)
    async def get_offer_mappings(
        self,
        business_id: str,
        limit: int = 100,
        page_token: Optional[str] = None,
        card_statuses: Optional[list[str]] = None,
        archived: bool = False,
    ) -> dict:
        """
        Список товаров в каталоге Яндекса (offer-mappings).
        Показывает реальные карточки на витрине ЛК.

        Args:
            business_id: ID кабинета
            limit: до 100 на страницу
            page_token: токен пагинации
            card_statuses: фильтр по статусам карточек (HAS_CARD_*, NO_CARD_*)
            archived: true — из архива
        """
        account = None
        for acc in settings.yandex_accounts:
            if acc.business_id == business_id:
                account = acc
                break
        if not account:
            raise ValueError(f"Unknown business_id: {business_id}")

        url = f"/v2/businesses/{business_id}/offer-mappings"
        params = {"limit": min(limit, 100)}
        if page_token:
            params["pageToken"] = page_token

        body: dict = {}
        if archived:
            body["archived"] = True
        if card_statuses:
            body["cardStatuses"] = card_statuses

        logger.info(f"[YANDEX] POST {url} | statuses={card_statuses}")

        response = await self.client.post(
            url,
            params=params,
            json=body if body else None,
            headers=self._get_headers(account),
        )
        response.raise_for_status()

        result = response.json()
        items = result.get("result", {}).get("offerMappings", [])
        logger.info(f"[YANDEX] 📥 Got {len(items)} offer-mappings")
        return result
    
    async def close(self):
        """Закрытие HTTP-клиента"""
        await self.client.aclose()


class MockYandexClient:
    """
    Мок-клиент для тестирования (🔥 РЕЖИМ ЕБАША В КОНСОЛЬ).
    
    Эмулирует все методы RealYandexClient, логирует запросы в консоль,
    но не делает реальных HTTP-запросов к Яндексу.
    """
    
    async def deliver_digital_goods(
        self,
        campaign_id: str,
        order_id: str,
        items: list[dict],
    ) -> dict:
        logger.info(f"[MOCK_YANDEX] POST /v2/campaigns/{campaign_id}/orders/{order_id}/deliverDigitalGoods")
        for item in items:
            logger.info(f"[MOCK_YANDEX] 🎁 Item {item['id']}: codes={item['codes']}")
            logger.info(f"[MOCK_YANDEX] 📝 Slip: {item['slip'][:100]}...")
        logger.info("[MOCK_YANDEX] ✅ Яндекс ответил: {'status': 'OK'} (письмо 'отправлено' покупателю)")
        return {"status": "OK"}
    
    async def get_orders(
        self,
        business_id: str,
        campaign_ids: list[str],
        statuses: Optional[list[str]] = None,
        limit: int = 50,
        page_token: Optional[str] = None,
    ) -> dict:
        logger.info(f"[MOCK_YANDEX] POST /v1/businesses/{business_id}/orders | campaigns={campaign_ids}, statuses={statuses}")
        logger.info("[MOCK_YANDEX] ✅ Найдено 0 новых заказов (mock)")
        return {"result": {"orders": [], "paging": {}}}
    
    async def send_chat_message(
        self,
        business_id: str,
        chat_id: str,
        message_text: str,
    ) -> dict:
        logger.info(f"[MOCK_YANDEX] POST /v2/businesses/{business_id}/chats/message?chatId={chat_id}")
        logger.info(f"[MOCK_YANDEX] 💬 Message: {message_text[:100]}...")
        logger.info("[MOCK_YANDEX] ✅ Message 'sent' to Yandex chat")
        return {"success": True, "response": {"status": "OK"}}
    
    async def get_chats(
        self,
        business_id: str,
        limit: int = 20,
        filters: Optional[dict] = None,
    ) -> dict:
        logger.info(f"[MOCK_YANDEX] POST /v2/businesses/{business_id}/chats | filters={filters}")
        logger.info("[MOCK_YANDEX] ✅ Got 0 chats (mock)")
        return {"result": {"chats": [], "paging": {}}}
    
    async def update_offer_mappings(
        self,
        business_id: str,
        offer_mappings: list[dict],
    ) -> dict:
        logger.info(f"[MOCK_YANDEX] POST /v2/businesses/{business_id}/offer-mappings/update | offers={len(offer_mappings)}")
        for offer in offer_mappings[:3]:  # Логируем первые 3
            offer_id = offer.get("offer", {}).get("offerId", "unknown")
            logger.info(f"[MOCK_YANDEX] 📦 Offer: {offer_id}")
        logger.info("[MOCK_YANDEX] ✅ Offer mappings 'updated' (mock)")
        return {"result": {"offerIds": ["mock_offer_1", "mock_offer_2"]}}
    
    async def update_prices(
        self,
        campaign_id: str,
        prices: list[dict],
    ) -> dict:
        logger.info(f"[MOCK_YANDEX] POST /v2/campaigns/{campaign_id}/offer-prices/updates | prices={len(prices)}")
        for price in prices[:3]:
            logger.info(f"[MOCK_YANDEX] 💰 {price['offerId']}: {price['price']['value']} {price['price']['currencyId']}")
        logger.info("[MOCK_YANDEX] ✅ Prices 'updated' (mock)")
        return {"result": {"offers": []}}
    
    async def update_stocks(
        self,
        campaign_id: str,
        stocks: list[dict],
    ) -> dict:
        logger.info(f"[MOCK_YANDEX] PUT /campaigns/{campaign_id}/offers/stocks | stocks={len(stocks)}")
        for stock in stocks[:3]:
            logger.info(f"[MOCK_YANDEX] 📊 {stock['sku']}: count={stock['items'][0]['count']}")
        logger.info("[MOCK_YANDEX] ✅ Stocks 'updated' (mock)")
        return {"result": {"warehouses": []}}
    
    async def close(self):
        logger.info("[MOCK_YANDEX] Client closed")