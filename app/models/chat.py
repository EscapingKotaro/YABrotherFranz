# app/models/chat.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from app.database import Base

class Chat(Base):
    """Локальная тень чата из CRM (для идемпотентности и быстрого поиска)"""
    __tablename__ = "chats"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # === Идентификаторы ===
    yandex_campaign_id = Column(String, nullable=False, index=True)  # Для маппинга на конфиг
    crm_marketplace_name = Column(String, nullable=False)  # То, что летит в CRM
    
    yandex_chat_id = Column(String, nullable=False, index=True)  # ID чата в Яндексе
    external_chat_id = Column(String, nullable=True, index=True)  # Дубль для CRM
    
    crm_chat_id = Column(Integer, nullable=True)  # ID чата в CRM (после создания)
    public_token = Column(String, nullable=True)  # Публичный токен для ссылки
    
    # === Метаданные ===
    customer_name = Column(String, nullable=True)
    product_name = Column(Text, nullable=True)
    platform = Column(String, nullable=True)  # ps5, switch и т.д.
    
    is_active = Column(Boolean, default=True)
    is_priority = Column(Boolean, default=False)
    is_english = Column(Boolean, default=False)
    
    # === Временные метки ===
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_sync_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_activity = Column(DateTime(timezone=True), server_default=func.now())
    def __str__(self):
        return f"Чат #{self.id} | {self.customer_name or 'Неизвестный'} ({self.crm_marketplace_name})"



class ChatMessage(Base):
    """Локальная тень сообщения (для идемпотентности и истории)"""
    __tablename__ = "chat_messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=False, index=True)
    
    # === Контент ===
    sender = Column(String, nullable=False)  # 'customer', 'manager', 'system'
    text = Column(Text, nullable=True)
    
    # === Идентификаторы для идемпотентности ===
    yandex_message_id = Column(String, nullable=True, index=True)  # ID сообщения в Яндексе
    crm_message_id = Column(Integer, nullable=True)  # ID сообщения в CRM
    external_message_id = Column(String, nullable=True, index=True)  # Для CRM API
    
    # === Статусы ===
    status = Column(String, default="pending")  # pending, sent_to_crm, sent_to_yandex, failed
    error_message = Column(Text, nullable=True)
    
    # === Временные метки ===
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    sent_to_crm_at = Column(DateTime(timezone=True), nullable=True)
    sent_to_yandex_at = Column(DateTime(timezone=True), nullable=True)

    def __str__(self):
        return f"Сообщение #{self.id} от {self.sender} ({self.status})"
