# app/schemas/yandex_webhook.py
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class OrderItemDTO(BaseModel):
    """Товар в составе заказа"""
    id: int = Field(..., description="ID товара в заказе (integer!)")
    offerId: str = Field(..., description="Наш SKU (cndk-...)")
    offerName: str = Field(..., description="Название товара")
    count: int = Field(default=1)
    price: float = Field(default=0)


class OrderBuyerDTO(BaseModel):
    """Покупатель"""
    id: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    middleName: Optional[str] = None


class OrderWebhookDTO(BaseModel):
    """Тело вебхука от Яндекс Маркета (без campaign_id — он в URL)"""
    orderId: int = Field(..., description="ID заказа")
    orderStatus: str = Field(..., description="PROCESSING, DELIVERED, CANCELLED и т.д.")
    orderSubstatus: Optional[str] = None
    items: list[OrderItemDTO] = Field(default_factory=list)
    buyer: Optional[OrderBuyerDTO] = None
    itemsTotal: float = Field(default=0)
    creationDate: Optional[str] = None
    updateDate: Optional[str] = None
    currency: str = Field(default="RUB")
    
    class Config:
        extra = "allow"  # Разрешаем дополнительные поля от Яндекса