# app/services/clients/crm_client.py
import httpx
import logging
from typing import Optional, List
from app.config import settings
from app.schemas.crm_api import (
    CreateChatRequest, CreateChatResponse,
    AddMessageRequest, AddMessageResponse,
    PendingTasksResponse, UpdateTaskStatusRequest
)
from app.core.retry import retry_with_backoff

logger = logging.getLogger(__name__)

class RealCrmClient:
    """Реальный клиент для работы с CRM API"""
    
    def __init__(self):
        self.base_url = settings.crm_api_url.rstrip("/")
        self.api_key = settings.crm_api_key
        self.timeout = httpx.Timeout(10.0, connect=5.0)
        
        # HTTP-клиент с пулингом соединений
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
        )
    
    @retry_with_backoff(max_retries=3, base_delay=1)
    async def create_chat(self, request: CreateChatRequest) -> CreateChatResponse:
        """Создание/восстановление чата в CRM"""
        logger.info(f"[CRM] Creating chat: marketplace={request.marketplace}, external_chat_id={request.external_chat_id}")
        
        response = await self.client.post(
            "/api/chats/create/",
            json=request.model_dump(exclude_none=True)
        )
        response.raise_for_status()
        
        result = CreateChatResponse(**response.json())
        logger.info(f"[CRM] ✅ Chat created/restored: chat_id={result.chat_id}, action={result.action}")
        return result
    
    @retry_with_backoff(max_retries=3, base_delay=1)
    async def add_message(self, request: AddMessageRequest) -> AddMessageResponse:
        """Добавление сообщения в чат"""
        logger.info(f"[CRM] Adding message: chat={request.external_chat_id}, sender={request.sender}")
        
        response = await self.client.post(
            "/api/chats/add-message/",
            json=request.model_dump(exclude_none=True)
        )
        response.raise_for_status()
        
        result = AddMessageResponse(**response.json())
        logger.info(f"[CRM] ✅ Message added: message_id={result.message_id}")
        return result
    
    @retry_with_backoff(max_retries=3, base_delay=1)
    async def get_pending_tasks(self, marketplace: str, limit: int = 50) -> PendingTasksResponse:
        """Получение задач на отправку сообщений"""
        logger.debug(f"[CRM] Fetching pending tasks for marketplace={marketplace}, limit={limit}")
        
        response = await self.client.get(
            "/api/tasks/pending/",
            params={"marketplace": marketplace, "limit": limit}
        )
        response.raise_for_status()
        
        result = PendingTasksResponse(**response.json())
        logger.info(f"[CRM] 📥 Found {result.count} pending tasks")
        return result
    
    @retry_with_backoff(max_retries=3, base_delay=1)
    async def update_task_status(self, request: UpdateTaskStatusRequest) -> dict:
        """Обновление статуса задачи"""
        logger.info(f"[CRM] Updating task {request.task_id} status to {request.status}")
        
        response = await self.client.post(
            "/api/tasks/update-status/",
            json=request.model_dump(exclude_none=True)
        )
        response.raise_for_status()
        
        result = response.json()
        logger.info(f"[CRM] ✅ Task {request.task_id} updated")
        return result
    
    async def close(self):
        """Закрытие HTTP-клиента"""
        await self.client.aclose()


class MockCrmClient:
    """Мок-клиент для тестирования (🔥 РЕЖИМ ЕБАША В КОНСОЛЬ)"""
    
    async def create_chat(self, request: CreateChatRequest) -> CreateChatResponse:
        logger.info(f"[MOCK_CRM] POST /api/chats/create/")
        logger.info(f"[MOCK_CRM] Payload: {request.model_dump()}")
        logger.info("[MOCK_CRM] ✅ Chat 'created' with id=99999, public_token='mock_token_123'")
        
        return CreateChatResponse(
            success=True,
            action="chat_created",
            message="Mock chat created",
            chat_id=99999,
            public_token="mock_token_123",
            external_chat_id=request.external_chat_id,
            chat_url=f"https://chats.mock.local/c/mock_token_123"
        )
    
    async def add_message(self, request: AddMessageRequest) -> AddMessageResponse:
        logger.info(f"[MOCK_CRM] POST /api/chats/add-message/")
        logger.info(f"[MOCK_CRM] Payload: {request.model_dump()}")
        logger.info("[MOCK_CRM] ✅ Message 'added' with id=88888")
        
        return AddMessageResponse(
            success=True,
            message="Mock message added",
            message_id=88888,
            chat_id=99999
        )
    
    async def get_pending_tasks(self, marketplace: str, limit: int = 50) -> PendingTasksResponse:
        logger.info(f"[MOCK_CRM] GET /api/tasks/pending/?marketplace={marketplace}&limit={limit}")
        logger.info("[MOCK_CRM] ✅ Returning 0 pending tasks (mock)")
        
        return PendingTasksResponse(
            success=True,
            marketplace=marketplace,
            count=0,
            tasks=[]
        )
    
    async def update_task_status(self, request: UpdateTaskStatusRequest) -> dict:
        logger.info(f"[MOCK_CRM] POST /api/tasks/update-status/")
        logger.info(f"[MOCK_CRM] Payload: {request.model_dump()}")
        logger.info("[MOCK_CRM] ✅ Task status 'updated'")
        
        return {"success": True, "message": "Mock task updated"}
    
    async def close(self):
        logger.info("[MOCK_CRM] Client closed")