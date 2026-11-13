# app/models/webhook.py
from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, Boolean
from sqlalchemy.sql import func
from app.database import Base

class WebhookLog(Base):
    """Журнал входящих вебхуков от Яндекс Маркета"""
    __tablename__ = "webhook_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Метаданные запроса
    campaign_id = Column(String, nullable=True, index=True)
    order_id = Column(String, nullable=True, index=True)
    webhook_type = Column(String, nullable=False)  # "order_status", "chat_message"

    # Содержимое
    payload = Column(JSON, nullable=True)
    signature_valid = Column(Boolean, default=False)

    # Результат обработки
    status = Column(String, nullable=False)  # "accepted", "ignored", "error"
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    def __str__(self):
        return f"Вебхука #{self.id}  {self.webhook_type} ({self.status})"
