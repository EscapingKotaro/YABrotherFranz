# app/admin/sqladmin_setup.py
from sqladmin import Admin, ModelView
from app.models.order import Order
from app.models.chat import Chat, ChatMessage
from app.models.catalog import CatalogItem, Listing, SyncState


class OrderAdmin(ModelView, model=Order):
    """Админка для заказов"""
    name = "Заказ"
    name_plural = "Заказы"
    icon = "fa-solid fa-cart-shopping"
    
    # Колонки в списке
    column_list = [
        Order.id,
        Order.order_id,
        Order.campaign_id,
        Order.status,
        Order.code_value,
        Order.total_amount,
        Order.created_at,
        Order.delivered_at,
    ]
    
    # Поиск
    column_searchable_list = [Order.order_id, Order.code_value, Order.campaign_id]
    
    # Фильтры
    column_filters = [Order.status, Order.campaign_id, Order.created_at]
    
    # Сортировка
    column_default_sort = (Order.created_at, True)
    
    # Детальная страница
    column_details_list = [
        Order.id,
        Order.order_id,
        Order.campaign_id,
        Order.customer_id,
        Order.status,
        Order.items_data,
        Order.total_amount,
        Order.currency,
        Order.code_id,
        Order.code_value,
        Order.created_at,
        Order.delivered_at,
        Order.updated_at,
    ]
    
    # Запрет на редактирование (только просмотр)
    can_create = False
    can_edit = False
    can_delete = False


class ChatAdmin(ModelView, model=Chat):
    """Админка для чатов"""
    name = "Чат"
    name_plural = "Чаты"
    icon = "fa-solid fa-comments"
    
    column_list = [
        Chat.id,
        Chat.yandex_chat_id,
        Chat.crm_marketplace_name,
        Chat.customer_name,
        Chat.platform,
        Chat.is_active,
        Chat.last_activity,
    ]
    
    column_searchable_list = [Chat.yandex_chat_id, Chat.customer_name, Chat.crm_marketplace_name]
    column_filters = [Chat.crm_marketplace_name, Chat.platform, Chat.is_active]
    column_default_sort = (Chat.last_activity, True)
    
    can_create = False
    can_edit = False
    can_delete = False


class ChatMessageAdmin(ModelView, model=ChatMessage):
    """Админка для сообщений"""
    name = "Сообщение"
    name_plural = "Сообщения"
    icon = "fa-solid fa-message"
    
    column_list = [
        ChatMessage.id,
        ChatMessage.chat_id,
        ChatMessage.sender,
        ChatMessage.text,
        ChatMessage.status,
        ChatMessage.created_at,
    ]
    
    column_searchable_list = [ChatMessage.text, ChatMessage.yandex_message_id]
    column_filters = [ChatMessage.sender, ChatMessage.status]
    column_default_sort = (ChatMessage.created_at, True)
    
    can_create = False
    can_edit = False
    can_delete = False


class CatalogItemAdmin(ModelView, model=CatalogItem):
    """Админка для товаров каталога"""
    name = "Товар"
    name_plural = "Товары"
    icon = "fa-solid fa-box"
    
    column_list = [
        CatalogItem.id,
        CatalogItem.channel_id,
        CatalogItem.channel_slot_id,
        CatalogItem.product_name,
        CatalogItem.publish,
        CatalogItem.withdraw,
        CatalogItem.target_amount,
        CatalogItem.updated_at,
    ]
    
    column_searchable_list = [CatalogItem.product_name, CatalogItem.channel_slot_id]
    column_filters = [CatalogItem.channel_id, CatalogItem.publish, CatalogItem.withdraw]
    
    can_create = False
    can_edit = False
    can_delete = False


class ListingAdmin(ModelView, model=Listing):
    """Админка для объявлений"""
    name = "Объявление"
    name_plural = "Объявления"
    icon = "fa-solid fa-store"
    
    column_list = [
        Listing.id,
        Listing.external_id,
        Listing.channel_id,
        Listing.status,
        Listing.reported_price_amount,
        Listing.consecutive_error_count,
        Listing.updated_at,
    ]
    
    column_searchable_list = [Listing.external_id]
    column_filters = [Listing.channel_id, Listing.status]
    
    can_create = False
    can_edit = False
    can_delete = False


class SyncStateAdmin(ModelView, model=SyncState):
    """Админка для состояния синхронизации"""
    name = "Синхронизация"
    name_plural = "Синхронизации"
    icon = "fa-solid fa-sync"
    
    column_list = [
        SyncState.id,
        SyncState.channel_id,
        SyncState.next_cursor,
        SyncState.module_declaration_revision,
        SyncState.last_sync_at,
    ]
    
    column_searchable_list = [SyncState.channel_id]
    
    can_create = False
    can_edit = False
    can_delete = False


def setup_admin(app):
    """Подключение SQLAdmin к FastAPI"""
    admin = Admin(
        app,
        engine=None,  # Используем async engine из database.py
        base_url="/admin",
        title="Yandex Market Client — Админка",
        logo_url=None,
    )
    
    # Регистрируем модели
    admin.add_view(OrderAdmin)
    admin.add_view(ChatAdmin)
    admin.add_view(ChatMessageAdmin)
    admin.add_view(CatalogItemAdmin)
    admin.add_view(ListingAdmin)
    admin.add_view(SyncStateAdmin)
    
    return admin