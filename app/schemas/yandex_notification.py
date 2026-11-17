# app/schemas/yandex_notification.py
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime


class NotificationOrderItemDTO(BaseModel):
    """Товар в уведомлении о заказе"""
    offerId: str = Field(..., description="Наш SKU (cndk-...)")
    count: int = Field(default=1)


class NotificationOrderLineServiceDTO(BaseModel):
    """Услуга в заказе"""
    itemId: int
    serviceArticle: Optional[str] = None


class BaseNotificationDTO(BaseModel):
    """Базовая структура уведомления"""
    notificationType: str
    campaignId: Optional[int] = None
    orderId: Optional[int] = None

    class Config:
        extra = "allow"


class PingNotificationDTO(BaseNotificationDTO):
    """Проверочное уведомление"""
    notificationType: Literal["PING"]
    time: Optional[str] = None


class OrderCreatedNotificationDTO(BaseNotificationDTO):
    """Уведомление о создании заказа"""
    notificationType: Literal["ORDER_CREATED"]
    orderId: int
    campaignId: int
    items: list[NotificationOrderItemDTO] = Field(default_factory=list)
    createdAt: Optional[str] = None
    orderLineServices: Optional[list[NotificationOrderLineServiceDTO]] = None


class OrderStatusUpdatedNotificationDTO(BaseNotificationDTO):
    """Уведомление об изменении статуса заказа"""
    notificationType: Literal["ORDER_STATUS_UPDATED"]
    orderId: int
    campaignId: int
    status: str  # PROCESSING, DELIVERED, CANCELLED и т.д.
    substatus: Optional[str] = None  # STARTED, READY_TO_SHIP и т.д.
    updatedAt: Optional[str] = None


# Union тип для всех уведомлений
YandexNotificationDTO = OrderCreatedNotificationDTO | OrderStatusUpdatedNotificationDTO | PingNotificationDTO