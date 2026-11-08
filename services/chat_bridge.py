# app/services/chat_bridge.py
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.chat import Chat, ChatMessage
from app.schemas.crm_api import (
    CreateChatRequest,
    AddMessageRequest,
    SenderType,
    UpdateTaskStatusRequest,
)
from app.services.clients.factory import get_crm_client, get_yandex_client

logger = logging.getLogger(__name__)


class ChatBridgeService:
    """
    Сервис-мост между Яндекс Маркетом и CRM.
    
    Отвечает за:
    1. Прием сообщений из Яндекса и отправку в CRM
    2. Прием задач из CRM и отправку ответов в Яндекс
    3. Поддержание идемпотентности через локальную БД
    """
    
    def __init__(self):
        self.crm_client = get_crm_client()
        self.yandex_client = get_yandex_client()
    
    async def process_incoming_message(
        self,
        session: AsyncSession,
        campaign_id: str,
        yandex_chat_id: str,
        yandex_message_id: str,
        sender: str,  # 'customer' или 'manager'
        text: str,
        customer_name: str,
        sent_at: Optional[datetime] = None,
        product_name: Optional[str] = None,
        platform: Optional[str] = None,
    ) -> dict:
        """
        Обработка входящего сообщения из Яндекса → отправка в CRM.
        
        Args:
            campaign_id: ID кампании Яндекса (для маппинга на CRM marketplace)
            yandex_chat_id: ID чата в Яндексе
            yandex_message_id: ID сообщения в Яндексе (для идемпотентности)
            sender: 'customer' или 'manager'
            text: Текст сообщения
            customer_name: Имя клиента
            sent_at: Время отправки (если None, берем текущее)
            product_name: Название товара (если есть)
            platform: Платформа (ps5, switch и т.д.)
        
        Returns:
            dict с результатом операции
        """
        
        # 1. Определяем crm_marketplace_name из конфига
        account_config = settings.accounts_by_campaign.get(campaign_id)
        if not account_config:
            logger.error(f"[ChatBridge] Unknown campaign_id: {campaign_id}")
            return {"success": False, "error": "Unknown campaign_id"}
        
        crm_marketplace_name = account_config.crm_marketplace_name
        
        # 2. Проверяем идемпотентность: сообщение уже обработано?
        existing_message = await session.execute(
            select(ChatMessage).where(
                ChatMessage.yandex_message_id == yandex_message_id
            )
        )
        if existing_message.scalar_one_or_none():
            logger.info(f"[ChatBridge] Message {yandex_message_id} already processed, skipping")
            return {"success": True, "action": "skipped", "reason": "duplicate"}
        
        # 3. Ищем или создаем чат в локальной БД
        chat = await self._get_or_create_chat(
            session=session,
            campaign_id=campaign_id,
            crm_marketplace_name=crm_marketplace_name,
            yandex_chat_id=yandex_chat_id,
            customer_name=customer_name,
            product_name=product_name,
            platform=platform,
        )
        
        # 4. Создаем чат в CRM (или обновляем существующий)
        create_chat_req = CreateChatRequest(
            marketplace=crm_marketplace_name,
            chat_id=str(chat.id),  # Внутренний ID чата
            external_chat_id=yandex_chat_id,  # ID чата в Яндексе
            customer_name=customer_name,
            is_priority=False,  # Можно добавить логику приоритета
            is_english=False,  # Можно определять по языку сообщения
            platform=platform,
            product_name=product_name,
        )
        
        crm_chat_response = await self.crm_client.create_chat(create_chat_req)
        
        # 5. Обновляем локальный чат с данными из CRM
        chat.crm_chat_id = crm_chat_response.chat_id
        chat.public_token = crm_chat_response.public_token
        chat.last_sync_at = datetime.utcnow()
        await session.commit()
        
        logger.info(f"[ChatBridge] Chat synced to CRM: chat_id={chat.id}, crm_chat_id={crm_chat_response.chat_id}")
        
        # 6. Отправляем сообщение в CRM
        add_message_req = AddMessageRequest(
            marketplace=crm_marketplace_name,
            external_chat_id=yandex_chat_id,
            sender=SenderType.CUSTOMER if sender == "customer" else SenderType.MANAGER,
            text=text,
            sent_at=sent_at.isoformat() if sent_at else None,
            external_message_id=yandex_message_id,  # Для идемпотентности в CRM
        )
        
        crm_message_response = await self.crm_client.add_message(add_message_req)
        
        # 7. Сохраняем сообщение в локальной БД
        new_message = ChatMessage(
            chat_id=chat.id,
            sender=sender,
            text=text,
            yandex_message_id=yandex_message_id,
            crm_message_id=crm_message_response.message_id,
            external_message_id=yandex_message_id,
            status="sent_to_crm",
            sent_to_crm_at=datetime.utcnow(),
        )
        session.add(new_message)
        await session.commit()
        
        logger.info(f"[ChatBridge] ✅ Message sent to CRM: yandex_msg={yandex_message_id}, crm_msg={crm_message_response.message_id}")
        
        return {
            "success": True,
            "action": "sent",
            "chat_id": chat.id,
            "crm_chat_id": crm_chat_response.chat_id,
            "crm_message_id": crm_message_response.message_id,
        }
    
    async def process_outgoing_messages(
        self,
        session: AsyncSession,
        crm_marketplace_name: str,
    ) -> dict:
        """
        Обработка исходящих сообщений: CRM → Яндекс.
        
        Опрос CRM на наличие задач (pending tasks) и отправка ответов в Яндекс.
        
        Args:
            session: Сессия БД
            crm_marketplace_name: Название маркетплейса в CRM (например, 'yandex_msk_digital')
        
        Returns:
            dict со статистикой обработки
        """
        
        # 1. Определяем account_config по crm_marketplace_name
        account_config = None
        for acc in settings.yandex_accounts:
            if acc.crm_marketplace_name == crm_marketplace_name:
                account_config = acc
                break
        
        if not account_config:
            logger.error(f"[ChatBridge] Unknown crm_marketplace_name: {crm_marketplace_name}")
            return {"success": False, "error": "Unknown marketplace"}
        
        campaign_id = account_config.campaign_id
        business_id = account_config.business_id
        
        # 2. Получаем задачи из CRM
        pending_tasks_response = await self.crm_client.get_pending_tasks(
            marketplace=crm_marketplace_name,
            limit=settings.crm_batch_size,
        )
        
        if not pending_tasks_response.tasks:
            logger.debug(f"[ChatBridge] No pending tasks for {crm_marketplace_name}")
            return {"success": True, "processed": 0, "sent": 0, "failed": 0}
        
        logger.info(f"[ChatBridge] 📥 Found {len(pending_tasks_response.tasks)} pending tasks for {crm_marketplace_name}")
        
        stats = {"processed": 0, "sent": 0, "failed": 0}
        
        # 3. Обрабатываем каждую задачу
        for task in pending_tasks_response.tasks:
            stats["processed"] += 1
            
            try:
                # Извлекаем данные из задачи
                task_id = task.task_id
                chat_data = task.chat
                message_data = task.message
                
                yandex_chat_id = chat_data.get("external_chat_id") or chat_data.get("chat_id")
                message_text = message_data.get("text", "")
                external_message_id = message_data.get("external_message_id")
                
                if not yandex_chat_id:
                    logger.error(f"[ChatBridge] Task {task_id} has no yandex_chat_id")
                    stats["failed"] += 1
                    continue
                
                # 4. Отправляем сообщение в Яндекс
                # Используем метод YandexClient для отправки сообщения в чат
                # (этот метод нужно будет добавить в yandex_client.py)
                yandex_response = await self.yandex_client.send_chat_message(
                    business_id=business_id,
                    chat_id=yandex_chat_id,
                    message_text=message_text,
                )
                
                if yandex_response.get("success"):
                    # 5. Успех → обновляем статус задачи в CRM
                    update_task_req = UpdateTaskStatusRequest(
                        task_id=task_id,
                        status="sent",
                        external_message_id=external_message_id,
                    )
                    await self.crm_client.update_task_status(update_task_req)
                    
                    # 6. Сохраняем сообщение в локальной БД
                    chat = await session.execute(
                        select(Chat).where(Chat.yandex_chat_id == yandex_chat_id)
                    )
                    chat_obj = chat.scalar_one_or_none()
                    
                    if chat_obj:
                        new_message = ChatMessage(
                            chat_id=chat_obj.id,
                            sender="manager",
                            text=message_text,
                            external_message_id=external_message_id,
                            status="sent_to_yandex",
                            sent_to_yandex_at=datetime.utcnow(),
                        )
                        session.add(new_message)
                        await session.commit()
                    
                    stats["sent"] += 1
                    logger.info(f"[ChatBridge] ✅ Task {task_id} sent to Yandex chat {yandex_chat_id}")
                else:
                    # 7. Ошибка → обновляем статус задачи в CRM
                    error_message = yandex_response.get("error", "Unknown error")
                    update_task_req = UpdateTaskStatusRequest(
                        task_id=task_id,
                        status="failed",
                        error_message=error_message,
                    )
                    await self.crm_client.update_task_status(update_task_req)
                    
                    stats["failed"] += 1
                    logger.error(f"[ChatBridge] ❌ Task {task_id} failed: {error_message}")
            
            except Exception as e:
                logger.error(f"[ChatBridge] Exception processing task {task.task_id}: {e}")
                stats["failed"] += 1
                
                # Пытаемся обновить статус задачи в CRM
                try:
                    update_task_req = UpdateTaskStatusRequest(
                        task_id=task.task_id,
                        status="failed",
                        error_message=str(e),
                    )
                    await self.crm_client.update_task_status(update_task_req)
                except:
                    pass
        
        logger.info(f"[ChatBridge] 📊 Stats: processed={stats['processed']}, sent={stats['sent']}, failed={stats['failed']}")
        
        return {"success": True, **stats}
    
    async def _get_or_create_chat(
        self,
        session: AsyncSession,
        campaign_id: str,
        crm_marketplace_name: str,
        yandex_chat_id: str,
        customer_name: str,
        product_name: Optional[str] = None,
        platform: Optional[str] = None,
    ) -> Chat:
        """
        Поиск или создание чата в локальной БД.
        """
        
        # Ищем существующий чат
        result = await session.execute(
            select(Chat).where(Chat.yandex_chat_id == yandex_chat_id)
        )
        chat = result.scalar_one_or_none()
        
        if chat:
            # Обновляем метаданные, если они изменились
            updated = False
            if customer_name and chat.customer_name != customer_name:
                chat.customer_name = customer_name
                updated = True
            if product_name and chat.product_name != product_name:
                chat.product_name = product_name
                updated = True
            if platform and chat.platform != platform:
                chat.platform = platform
                updated = True
            
            if updated:
                chat.last_sync_at = datetime.utcnow()
                await session.commit()
            
            return chat
        
        # Создаем новый чат
        new_chat = Chat(
            yandex_campaign_id=campaign_id,
            crm_marketplace_name=crm_marketplace_name,
            yandex_chat_id=yandex_chat_id,
            external_chat_id=yandex_chat_id,  # Дубль для CRM
            customer_name=customer_name,
            product_name=product_name,
            platform=platform,
            is_active=True,
        )
        session.add(new_chat)
        await session.commit()
        await session.refresh(new_chat)
        
        logger.info(f"[ChatBridge] Created new chat: id={new_chat.id}, yandex_chat_id={yandex_chat_id}")
        
        return new_chat