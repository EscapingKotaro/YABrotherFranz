# app/admin/sqladmin_setup.py
"""
Read-only админка SQLAdmin + авторизация.

ВАЖНО:
- Все views read-only (can_create/edit/delete = False) — смотрим и ищем, не правим.
- column_filters только для String/Boolean через SelectFilter/BooleanFilter.
  DateTime в column_filters НЕ класть — SQLAdmin 0.16 на них падает (500).
- JSON-колонки (items_data, axis_values, presentation_gallery, covered_channel_slot_ids)
  в column_list НЕ класть — только в column_details_list.
- Сессии админки подписывает secret_key, переданный в Admin().
  SessionMiddleware в main.py добавлять НЕ нужно (sqladmin ставит свой сам).
"""

from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqladmin.filters import BooleanFilter, SelectFilter
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
    """
    Простая логин-форма: username/password из .env (ADMIN_USERNAME / ADMIN_PASSWORD).
    Сессия хранится в signed cookie sqladmin (secret_key из Admin()).
    """

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
# View'ы
# =====================================================================

class OrderAdmin(ModelView, model=Order):
    name = "Заказ"
    name_plural = "Заказы"
    icon = "fa-solid fa-cart-shopping"

    column_list = [
        Order.id,
        Order.order_id,
        Order.campaign_id,
        Order.status,
        Order.code_value,
        Order.total_amount,
        Order.currency,
        Order.created_at,
        Order.delivered_at,
    ]

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

    # Поиск по строковым колонкам
    column_searchable_list = [
        Order.order_id,
        Order.code_value,
        Order.campaign_id,
        Order.customer_id,
    ]

    # Фильтры: только поддерживаемые типы
    column_filters = [
        SelectFilter(
            field=Order.status,
            title="Статус",
            options=[
                ("RECEIVED", "RECEIVED"),
                ("PROCESSING", "PROCESSING"),
                ("DELIVERY_PENDING", "DELIVERY_PENDING"),
                ("DELIVERED", "DELIVERED"),
                ("MANUAL_PENDING", "MANUAL_PENDING"),
                ("FAILED_FULFILLMENT", "FAILED_FULFILLMENT"),
                ("CANCELLED", "CANCELLED"),
            ],
        ),
        SelectFilter(field=Order.campaign_id, title="Кампания", options=[]),
    ]

    column_default_sort = (Order.created_at, True)
    page_size = 25

    can_create = False
    can_edit = False
    can_delete = False


class ChatAdmin(ModelView, model=Chat):
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
        Chat.is_priority,
        Chat.last_activity,
    ]

    column_details_list = [
        Chat.id,
        Chat.yandex_campaign_id,
        Chat.crm_marketplace_name,
        Chat.yandex_chat_id,
        Chat.external_chat_id,
        Chat.crm_chat_id,
        Chat.public_token,
        Chat.customer_name,
        Chat.product_name,
        Chat.platform,
        Chat.is_active,
        Chat.is_priority,
        Chat.is_english,
        Chat.created_at,
        Chat.last_sync_at,
        Chat.last_activity,
    ]

    column_searchable_list = [
        Chat.yandex_chat_id,
        Chat.customer_name,
        Chat.crm_marketplace_name,
        Chat.external_chat_id,
    ]

    column_filters = [
        BooleanFilter(field=Chat.is_active, title="Активен"),
        BooleanFilter(field=Chat.is_priority, title="Приоритет"),
        SelectFilter(field=Chat.crm_marketplace_name, title="Площадка CRM", options=[]),
        SelectFilter(field=Chat.platform, title="Платформа", options=[]),
    ]

    column_default_sort = (Chat.last_activity, True)
    page_size = 25

    can_create = False
    can_edit = False
    can_delete = False


class ChatMessageAdmin(ModelView, model=ChatMessage):
    name = "Сообщение"
    name_plural = "Сообщения"
    icon = "fa-solid fa-message"

    column_list = [
        ChatMessage.id,
        ChatMessage.chat_id,
        ChatMessage.sender,
        ChatMessage.status,
        ChatMessage.yandex_message_id,
        ChatMessage.created_at,
    ]

    column_details_list = [
        ChatMessage.id,
        ChatMessage.chat_id,
        ChatMessage.sender,
        ChatMessage.text,
        ChatMessage.yandex_message_id,
        ChatMessage.crm_message_id,
        ChatMessage.external_message_id,
        ChatMessage.status,
        ChatMessage.error_message,
        ChatMessage.created_at,
        ChatMessage.sent_to_crm_at,
        ChatMessage.sent_to_yandex_at,
    ]

    column_searchable_list = [
        ChatMessage.yandex_message_id,
        ChatMessage.external_message_id,
    ]

    column_filters = [
        SelectFilter(
            field=ChatMessage.sender,
            title="Отправитель",
            options=[
                ("customer", "customer"),
                ("manager", "manager"),
                ("system", "system"),
            ],
        ),
        SelectFilter(
            field=ChatMessage.status,
            title="Статус",
            options=[
                ("pending", "pending"),
                ("sent_to_crm", "sent_to_crm"),
                ("sent_to_yandex", "sent_to_yandex"),
                ("failed", "failed"),
            ],
        ),
    ]

    column_default_sort = (ChatMessage.created_at, True)
    page_size = 50

    can_create = False
    can_edit = False
    can_delete = False


class CatalogItemAdmin(ModelView, model=CatalogItem):
    name = "Товар"
    name_plural = "Товары"
    icon = "fa-solid fa-box"

    column_list = [
        CatalogItem.id,
        CatalogItem.channel_id,
        CatalogItem.channel_slot_id,
        CatalogItem.product_name,
        CatalogItem.product_variant_name,
        CatalogItem.publish,
        CatalogItem.withdraw,
        CatalogItem.target_amount,
        CatalogItem.updated_at,
    ]

    column_details_list = [
        CatalogItem.id,
        CatalogItem.channel_id,
        CatalogItem.channel_slot_id,
        CatalogItem.sellable_position_id,
        CatalogItem.product_name,
        CatalogItem.product_variant_name,
        CatalogItem.product_type_identifier,
        CatalogItem.axis_values,
        CatalogItem.publish,
        CatalogItem.withdraw,
        CatalogItem.intent_reason,
        CatalogItem.stale,
        CatalogItem.target_amount,
        CatalogItem.target_currency,
        CatalogItem.presentation_title,
        CatalogItem.presentation_text,
        CatalogItem.presentation_gallery,
        CatalogItem.created_at,
        CatalogItem.updated_at,
    ]

    column_searchable_list = [
        CatalogItem.product_name,
        CatalogItem.product_variant_name,
    ]

    column_filters = [
        BooleanFilter(field=CatalogItem.publish, title="Publish"),
        BooleanFilter(field=CatalogItem.withdraw, title="Withdraw"),
        BooleanFilter(field=CatalogItem.stale, title="Stale"),
        SelectFilter(field=CatalogItem.channel_id, title="Канал", options=[]),
    ]

    column_default_sort = (CatalogItem.updated_at, True)
    page_size = 50

    can_create = False
    can_edit = False
    can_delete = False


class ListingAdmin(ModelView, model=Listing):
    name = "Объявление"
    name_plural = "Объявления"
    icon = "fa-solid fa-store"

    column_list = [
        Listing.id,
        Listing.external_id,
        Listing.channel_id,
        Listing.status,
        Listing.reported_price_amount,
        Listing.reported_price_currency,
        Listing.consecutive_error_count,
        Listing.updated_at,
    ]

    column_details_list = [
        Listing.id,
        Listing.external_id,
        Listing.channel_id,
        Listing.covered_channel_slot_ids,
        Listing.price_sellable_position_id,
        Listing.status,
        Listing.reported_price_amount,
        Listing.reported_price_currency,
        Listing.presentation_title,
        Listing.presentation_text,
        Listing.presentation_images,
        Listing.last_error_text,
        Listing.consecutive_error_count,
        Listing.removal_requested_at,
        Listing.created_at,
        Listing.updated_at,
    ]

    column_searchable_list = [
        Listing.external_id,
    ]

    column_filters = [
        SelectFilter(
            field=Listing.status,
            title="Статус",
            options=[
                ("published", "published"),
                ("publishing", "publishing"),
                ("hidden", "hidden"),
                ("expected", "expected"),
                ("removed", "removed"),
            ],
        ),
        SelectFilter(field=Listing.channel_id, title="Канал", options=[]),
    ]

    column_default_sort = (Listing.updated_at, True)
    page_size = 50

    can_create = False
    can_edit = False
    can_delete = False


class SyncStateAdmin(ModelView, model=SyncState):
    name = "Синхронизация"
    name_plural = "Синхронизации"
    icon = "fa-solid fa-arrows-rotate"

    column_list = [
        SyncState.id,
        SyncState.channel_id,
        SyncState.module_declaration_revision,
        SyncState.executor_state_revision,
        SyncState.last_sync_at,
    ]

    column_details_list = [
        SyncState.id,
        SyncState.channel_id,
        SyncState.next_cursor,
        SyncState.module_declaration_revision,
        SyncState.executor_state_revision,
        SyncState.last_sync_at,
        SyncState.created_at,
    ]

    # channel_id — int, в searchable не кладём (SQLAdmin на int-поиск ругается)
    column_searchable_list = []

    column_filters = [
        SelectFilter(field=SyncState.channel_id, title="Канал", options=[]),
    ]

    column_default_sort = (SyncState.last_sync_at, True)
    page_size = 25

    can_create = False
    can_edit = False
    can_delete = False


# =====================================================================
# Подключение
# =====================================================================

def setup_admin(app) -> Admin:
    """
    Монтирует SQLAdmin на /admin с авторизацией.
    secret_key передаётся сюда — sqladmin сам ставит SessionMiddleware.
    SessionMiddleware в main.py добавлять НЕ нужно.
    """
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
