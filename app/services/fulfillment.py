# app/services/fulfillment.py
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.order import Order
from app.schemas.yandex_webhook import OrderWebhookDTO
from app.services.clients.factory import get_code_api_client, get_yandex_client
from app.config import settings

logger = logging.getLogger(__name__)


class FulfillmentService:
    """
    Сервис обработки заказов: проверка склада -> выпуск кода -> доставка в Яндекс.
    """
    
    def __init__(self):
        self.code_client = get_code_api_client()
        self.yandex_client = get_yandex_client()
    
    async def deliver_order(
        self,
        session: AsyncSession,
        order_id: str,
        campaign_id: str,
    ) -> dict:
        """
        Полный цикл выдачи заказа.
        
        Args:
            session: Сессия БД
            order_id: ID заказа Яндекса
            campaign_id: ID кампании (для выбора аккаунта)
        
        Returns:
            {"success": bool, "code": str | None, "error": str | None}
        """
        
        # 1. Загружаем заказ из БД (должен быть создан при приеме вебхука)
        result = await session.execute(
            select(Order).where(Order.order_id == order_id)
        )
        order = result.scalar_one_or_none()
        
        if not order:
            logger.error(f"[Fulfillment] Order {order_id} not found in DB")
            return {"success": False, "error": "Order not found"}
        
        if order.status == "DELIVERED":
            logger.info(f"[Fulfillment] Order {order_id} already delivered")
            return {"success": True, "status": "already_delivered"}
        
        # Проверяем дедлайн (30 минут по доке Яндекса)
        if order.created_at:
            now_utc = datetime.now(timezone.utc)
            created_at_utc = order.created_at
            
            # Если время из БД вдруг без часового пояса, делаем его UTC
            if created_at_utc.tzinfo is None:
                created_at_utc = created_at_utc.replace(tzinfo=timezone.utc)
            
            if (now_utc - created_at_utc) > timedelta(minutes=25):
                logger.warning(f"[Fulfillment] ⚠️ Order {order_id} is close to deadline!")
        
        try:
            # 2. Извлекаем данные товара из заказа
            # items_data хранится как JSON в модели Order
            items_data = order.items_data or []
            if not items_data:
                raise ValueError("No items in order data")
            
            # Берем первый товар (обычно один цифровой товар в заказе)
            item = items_data[0]
            offer_id = item.get("offerId") # Наш SKU (cndk-...)
            yandex_item_id = item.get("id") # Integer ID товара в заказе (критично!)
            
            # Парсим наш SKU cndk-{game_id}-{variant_id}-{console}-{tier}
            game_name = await self._get_game_name_by_offer_id(session, offer_id)
            platform, method = self._parse_platform_and_method(offer_id)
            
            if not game_name:
                raise ValueError(f"Could not determine game name for offer_id {offer_id}")
            
            logger.info(f"[Fulfillment] Processing item: game={game_name}, platform={platform}, method={method}")
            
            # 3. Проверка доступности (CanActivate)
            can_activate_resp = await self.code_client.can_activate(
                game_name=game_name,
                platform=platform,
                method=method,
            )
            
            if not can_activate_resp.get("canActivate"):
                reason = can_activate_resp.get("reason", "unknown")
                logger.error(f"[Fulfillment] Cannot activate: {reason}")
                # Статус MANUAL_PENDING будет обработан в воркере через DLQ/алерт
                raise Exception(f"No stock available: {reason}")
            
            # 4. Выпуск кода (Issue)
            issue_resp = await self.code_client.issue_code(
                marketplace="Yandex",
                platform=platform,
                game_name=game_name,
                task_number=order_id, # Идемпотентность!
                source_system_name="YandexMarketClient",
            )
            
            generated_code = issue_resp["code"]["code"]
            logger.info(f"[Fulfillment] Code issued: {generated_code}")
            
            # 5. Формируем payload для Яндекса
            slip_text = self._generate_slip_text(generated_code)
            activate_till = (datetime.now() + timedelta(days=14)).strftime('%Y-%m-%d')
            
            yandex_items = [{
                "id": yandex_item_id, # Integer!
                "codes": [generated_code],
                "slip": slip_text,
                "activate_till": activate_till
            }]
            
            # 6. Доставка в Яндекс
            await self.yandex_client.deliver_digital_goods(
                campaign_id=campaign_id,
                order_id=order_id,
                items=yandex_items,
            )
            
            # 7. Обновляем статус в БД
            order.status = "DELIVERED"
            order.code_value = generated_code
            order.delivered_at = datetime.now(timezone.utc)  # 🔥 ИСПРАВЛЕНО
            await session.commit()
            
            logger.info(f"[Fulfillment] ✅ Order {order_id} successfully delivered with code {generated_code}")
            
            return {"success": True, "code": generated_code}
            
        except Exception as e:
            logger.error(f"[Fulfillment] ❌ Error delivering order {order_id}: {e}")
            order.status = "FAILED_FULFILLMENT"
            await session.commit()
            raise e
    
    def _parse_platform_and_method(self, offer_id: str) -> tuple[str, str]:
        """
        Парсит platform и method из нашего SKU формата cndk-{...}-{console}-{tier}
        """
        parts = offer_id.split("-")
        console = parts[-2].lower() if len(parts) >= 2 else ""
        tier = parts[-1].lower() if len(parts) >= 1 else ""
        
        # Маппинг на Code API платформы
        if "ps" in console:
            platform = "PlayStation"
            method = "P3" if "prem" in tier else "P2"
        elif "switch" in console:
            platform = "Nintendo"
            method = "Prem" if "prem" in tier else "Normal"
        elif "xbox" in console:
            platform = "Xbox"
            method = "Prem" if "prem" in tier else "Normal"
        elif "steam" in console:
            platform = "Steam"
            method = "Prem" if "prem" in tier else "Normal"
        else:
            platform = "Other"
            method = "Normal"
            
        return platform, method
    
    async def _get_game_name_by_offer_id(self, session: AsyncSession, offer_id: str) -> Optional[str]:
        """
        Ищем название игры по нашему SKU в локальной тени каталога.
        """
        from app.models.catalog import CatalogItem
        
        # Offer ID обычно содержит sellable_position_id или product_variant_id
        # Упрощенный поиск: ищем в presentation_title
        result = await session.execute(
            select(CatalogItem).where(CatalogItem.presentation_title.contains(offer_id))
        )
        item = result.scalar_one_or_none()
        
        if item:
            return item.product_name
            
        # Если не нашли, можно попробовать распарсить ID из строки
        # Но лучше хранить маппинг offer_id -> game_name в отдельной таблице
        return None
    
    def _generate_slip_text(self, code: str) -> str:
        """
        Генерирует HTML-инструкцию для письма Яндекса.
        """
        portal_url = settings.ACTIVATION_PORTAL_URL if hasattr(settings, 'ACTIVATION_PORTAL_URL') else "https://systemseller.net/"
        
        return f"""
        <p>Спасибо за покупку!</p>
        <p>Ваш код активации: <b>{code}</b></p>
        <p>Для получения игры перейдите на страницу: <a href="{portal_url}">{portal_url}</a> и следуйте инструкции.</p>
        """