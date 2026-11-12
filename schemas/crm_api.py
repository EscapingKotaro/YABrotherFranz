from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum



class SenderType(str, Enum):
    CUSTOMER = "customer"
    MANAGER = "manager"
    SYSTEM = "system"

class CreateChatRequest(BaseModel):
    """Запрос на создание/восстановление чата в CRM"""
    marketplace: str = Field(..., description="api_name маркетплейса в CRM")
    chat_id: str = Field(..., description="Внутренний ID чата (например, order_id)")
    external_chat_id: str = Field(..., description="Внешний ID чата (например, yandex_chat_id)")
    customer_name: str = Field(..., description="Имя клиента")
    is_priority: bool = Field(default=False)
    is_english: bool = Field(default=False)
    platform: Optional[str] = Field(default=None, description="Платформа (ps5, switch и т.д.)")
    product_name: Optional[str] = Field(default=None, description="Название товара")
    code: Optional[str] = Field(default=None, description="Код активации (если есть)")

class CreateChatResponse(BaseModel):
    """Ответ от CRM после создания чата"""
    success: bool
    action: str  
    message: str
    chat_id: int
    public_token: str
    external_chat_id: str
    chat_url: Optional[str] = None
    product_platform: Optional[str] = None

class AddMessageRequest(BaseModel):
    """Запрос на добавление сообщения в чат"""
    marketplace: str
    chat_id: Optional[str] = None
    external_chat_id: Optional[str] = None
    sender: SenderType
    text: str
    sent_at: Optional[str] = None  # ISO 8601
    external_message_id: Optional[str] = None

class AddMessageResponse(BaseModel):
    """Ответ от CRM после добавления сообщения"""
    success: bool
    message: str
    message_id: int
    chat_id: int
    video_url: Optional[str] = None
    image_url: Optional[str] = None

class TaskInfo(BaseModel):
    """Информация о задаче на отправку сообщения"""
    task_id: int
    status: str  # "pending", "sent", "failed"
    created_at: Optional[str] = None
    scheduled_for: Optional[str] = None
    retry_count: int = 0
    error_message: Optional[str] = None
    
    chat: dict  # {chat_id, external_chat_id, customer_name, public_token}
    message: dict  # {message_id, external_message_id, sender, text, sent_at}

class PendingTasksResponse(BaseModel):
    """Ответ от CRM со списком задач на отправку"""
    success: bool
    marketplace: str
    count: int
    tasks: List[TaskInfo]

class UpdateTaskStatusRequest(BaseModel):
    """Запрос на обновление статуса задачи"""
    task_id: int
    status: str  # "sent", "failed"
    external_message_id: Optional[str] = None
    error_message: Optional[str] = None