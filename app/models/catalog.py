# app/models/catalog.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, Text, BigInteger
from sqlalchemy.sql import func
from app.database import Base


class SyncState(Base):
    """Состояние синхронизации для каждого канала CNDK"""
    __tablename__ = "sync_state"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(Integer, nullable=False, unique=True, index=True)
    
    # Курсор для GET /slots
    next_cursor = Column(String, nullable=True)
    
    # Ревизия объявления модуля (для идемпотентности PUT /module-declaration)
    module_declaration_revision = Column(Integer, default=1)
    
    # Ревизия состояния исполнителя
    executor_state_revision = Column(Integer, default=1)
    
    # Временные метки
    last_sync_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    def __str__(self):
        return f"Синхронизация канала #{self.channel_id}"


class CatalogItem(Base):
    """Локальная тень слота CNDK (для быстрого поиска и истории)"""
    __tablename__ = "catalog_items"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Идентификаторы CNDK
    channel_id = Column(Integer, nullable=False, index=True)
    channel_slot_id = Column(Integer, nullable=False, index=True)
    sellable_position_id = Column(Integer, nullable=False, index=True)
    
    # Метаданные товара
    product_name = Column(String, nullable=True)
    product_variant_name = Column(String, nullable=True)
    product_type_identifier = Column(String, default="game")
    
    # Оси (platform, price_group, tier, delivery_type)
    axis_values = Column(JSON, nullable=True)
    
    # Решение Core
    publish = Column(Boolean, default=False)
    withdraw = Column(Boolean, default=False)
    intent_reason = Column(String, nullable=True)
    stale = Column(Boolean, default=False)
    
    # Целевая цена
    target_amount = Column(String, nullable=True)  # "1990.00"
    target_currency = Column(String, nullable=True)  # "RUB"
    
    # Оформление
    presentation_title = Column(Text, nullable=True)
    presentation_text = Column(Text, nullable=True)
    presentation_gallery = Column(JSON, nullable=True)
    
    # Временные метки
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    def __str__(self):
        return f"Товар #{self.id} | {self.product_name or 'Без имени'}"



class Listing(Base):
    """Локальная тень объявления (карточки на площадке)"""
    __tablename__ = "listings"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Идентификаторы
    channel_id = Column(Integer, nullable=False, index=True)
    external_id = Column(String, nullable=False, unique=True, index=True)  # offerId в Яндексе
    
    # Связь со слотами
    covered_channel_slot_ids = Column(JSON, nullable=True)  # [3302, 3303]
    price_sellable_position_id = Column(Integer, nullable=True)
    
    # Статус
    status = Column(String, default="expected")  # published, publishing, hidden, expected, removed
    
    # Цена
    reported_price_amount = Column(String, nullable=True)
    reported_price_currency = Column(String, nullable=True)
    
    # Оформление (то, что реально на площадке)
    presentation_title = Column(Text, nullable=True)
    presentation_text = Column(Text, nullable=True)
    presentation_images = Column(JSON, nullable=True)
    
    # Ошибки
    last_error_text = Column(Text, nullable=True)
    consecutive_error_count = Column(Integer, default=0)
    
    # Запрос снятия
    removal_requested_at = Column(DateTime(timezone=True), nullable=True)
    
    # Временные метки
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    def __str__(self):
        return f"Объявление {self.external_id} ({self.status})"
