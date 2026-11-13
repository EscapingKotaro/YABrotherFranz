# app/admin/sqladmin_setup.py
"""
Read-only админка SQLAdmin + авторизация.
Упрощенная версия без сложных импортов фильтров, чтобы избежать ошибок версий.
"""

from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request

from app.config import settings
from app.database import engine
from app.models.order import Order
from app.models.chat import Chat, ChatMessage
from app.models.catalog import CatalogItem, Listing, SyncState


# =====================================================================
# Авторизация
# =====================================================================

class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = (form.get("username") or "").strip()
        password = form.get("password") or ""

        if username == settings.admin_username and password == settings.admin_password:
            request.session.update({"authenticated": True, "username": username})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return bool(request.session.get("authenticated", False))


# =====================================================================
# View'ы (Упрощенные, без ручных импортов фильтров)
# =====================================================================

class OrderAdmin(ModelView, model=Order):
    name = "Заказ"
    name_plural = "Заказы"
    icon = "fa-solid fa-cart-shopping"

    column_list = [Order.id, Order.order_id, Order.campaign_id, Order.status, Order.code_value, Order.total_amount, Order.created_at]
    column_details_list = [Order.id, Order.order_id, Order.campaign_id, Order.customer_id, Order.status, Order.total_amount, Order.currency, Order.code_id, Order.code_value, Order.created_at, Order.delivered_at]

    column_searchable_list = [Order.order_id, Order.code_value, Order.campaign_id]
    column_filters = [Order.status, Order.campaign_id]  # SQLAdmin сам создаст выпадающий список для этих полей!
    column_default_sort = (Order.created_at, True)
    page_size = 25

    can_create = False
    can_edit = False
    can_delete = False


class ChatAdmin(ModelView, model=Chat):
    name = "Чат"
    name_plural = "Чаты"
    icon = "fa-solid fa-comments"

    column_list = [Chat.id, Chat.yandex_chat_id, Chat.crm_marketplace_name, Chat.customer_name, Chat.platform, Chat.is_active, Chat.last_activity]
    column_details_list = [Chat.id, Chat.yandex_campaign_id, Chat.crm_marketplace_name, Chat.yandex_chat_id, Chat.external_chat_id, Chat.crm_chat_id, Chat.customer_name, Chat.product_name, Chat.platform, Chat.is_active, Chat.is_priority, Chat.last_activity]

    column_searchable_list = [Chat.yandex_chat_id, Chat.customer_name, Chat.crm_marketplace_name]
    column_filters = [Chat.crm_marketplace_name, Chat.platform, Chat.is_active]
    column_default_sort = (Chat.last_activity, True)
    page_size = 25

    can_create = False
    can_edit = False
    can_delete = False


class ChatMessageAdmin(ModelView, model=ChatMessage):
    name = "Сообщение"
    name_plural = "Сообщения"
    icon = "fa-solid fa-message"

    column_list = [ChatMessage.id, ChatMessage.chat_id, ChatMessage.sender, ChatMessage.status, ChatMessage.yandex_message_id, ChatMessage.created_at]
    column_details_list = [ChatMessage.id, ChatMessage.chat_id, ChatMessage.sender, ChatMessage.text, ChatMessage.yandex_message_id, ChatMessage.status, ChatMessage.error_message, ChatMessage.created_at]

    column_searchable_list = [ChatMessage.yandex_message_id, ChatMessage.external_message_id]
    column_filters = [ChatMessage.sender, ChatMessage.status]
    column_default_sort = (ChatMessage.created_at, True)
    page_size = 50

    can_create = False
    can_edit = False
    can_delete = False


class CatalogItemAdmin(ModelView, model=CatalogItem):
    name = "Товар"
    name_plural = "Товары"
    icon = "fa-solid fa-box"

    column_list = [CatalogItem.id, CatalogItem.channel_id, CatalogItem.channel_slot_id, CatalogItem.product_name, CatalogItem.publish, CatalogItem.withdraw, CatalogItem.target_amount, CatalogItem.updated_at]
    column_details_list = [CatalogItem.id, CatalogItem.channel_id, CatalogItem.channel_slot_id, CatalogItem.sellable_position_id, CatalogItem.product_name, CatalogItem.product_variant_name, CatalogItem.axis_values, CatalogItem.publish, CatalogItem.withdraw, CatalogItem.target_amount, CatalogItem.target_currency, CatalogItem.presentation_title, CatalogItem.updated_at]

    column_searchable_list = [CatalogItem.product_name, CatalogItem.product_variant_name]
    column_filters = [CatalogItem.channel_id, CatalogItem.publish, CatalogItem.withdraw]
    column_default_sort = (CatalogItem.updated_at, True)
    page_size = 50

    can_create = False
    can_edit = False
    can_delete = False


class ListingAdmin(ModelView, model=Listing):
    name = "Объявление"
    name_plural = "Объявления"
    icon = "fa-solid fa-store"

    column_list = [Listing.id, Listing.external_id, Listing.channel_id, Listing.status, Listing.reported_price_amount, Listing.consecutive_error_count, Listing.updated_at]
    column_details_list = [Listing.id, Listing.external_id, Listing.channel_id, Listing.covered_channel_slot_ids, Listing.status, Listing.reported_price_amount, Listing.reported_price_currency, Listing.presentation_title, Listing.last_error_text, Listing.consecutive_error_count, Listing.updated_at]

    column_searchable_list = [Listing.external_id]
    column_filters = [Listing.channel_id, Listing.status]
    column_default_sort = (Listing.updated_at, True)
    page_size = 50

    can_create = False
    can_edit = False
    can_delete = False


class SyncStateAdmin(ModelView, model=SyncState):
    name = "Синхронизация"
    name_plural = "Синхронизации"
    icon = "fa-solid fa-arrows-rotate"

    column_list = [SyncState.id, SyncState.channel_id, SyncState.module_declaration_revision, SyncState.executor_state_revision, SyncState.last_sync_at]
    column_details_list = [SyncState.id, SyncState.channel_id, SyncState.next_cursor, SyncState.module_declaration_revision, SyncState.executor_state_revision, SyncState.last_sync_at, SyncState.created_at]

    column_searchable_list = []
    column_filters = [SyncState.channel_id]
    column_default_sort = (SyncState.last_sync_at, True)
    page_size = 25

    can_create = False
    can_edit = False
    can_delete = False


# =====================================================================
# Подключение
# =====================================================================

def setup_admin(app) -> Admin:
    admin = Admin(
        app,
        engine=engine,
        base_url="/admin",
        title="Yandex Market Client",
        authentication_backend=AdminAuth(secret_key=settings.secret_key),
    )

    admin.add_view(OrderAdmin)
    admin.add_view(ChatAdmin)
    admin.add_view(ChatMessageAdmin)
    admin.add_view(CatalogItemAdmin)
    admin.add_view(ListingAdmin)
    admin.add_view(SyncStateAdmin)

    return admin
