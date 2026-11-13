# app/models/order.py
from sqlalchemy import Column, String, Integer, Float, JSON, DateTime
from sqlalchemy.sql import func
from app.database import Base


class Order(Base):
    """Заказ Яндекс Маркета"""
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Идентификаторы
    order_id = Column(String, unique=True, nullable=False, index=True)
    campaign_id = Column(String, nullable=False, index=True)
    customer_id = Column(String, nullable=True)
    
    # Статусы
    status = Column(String, nullable=False, default="RECEIVED")
    # RECEIVED, PROCESSING, DELIVERED, DELIVERY_PENDING, FAILED_FULFILLMENT, MANUAL_PENDING
    
    # Данные заказа
    items_data = Column(JSON, nullable=False)  # Массив товаров из webhook
    total_amount = Column(Float, nullable=True)
    currency = Column(String, default="RUB")
    
    # Код
    code_id = Column(String, nullable=True)  # ID кода из Code API
    code_value = Column(String, nullable=True)  # Сам код (ABCD-1234)
    
    # Временные метки
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    def __str__(self):
        return f"Заказ #{self.order_id}  {self.code_value} ({self.status})"
