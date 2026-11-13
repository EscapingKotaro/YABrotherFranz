# app/admin/sqladmin_setup.py
"""
Read-only админка SQLAdmin + авторизация.
Исправленная версия: все column_default_sort и searchable используют строки,
чтобы избежать AttributeError.split в SQLAdmin.
"""

from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request

from app.config import settings
from app.database import engine
from app.models.order import Order
from app.models.chat import Chat, ChatMessage
from app.models.catalog import CatalogItem, Listing, SyncState
from app.models.webhook import WebhookLog


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
# View'ы
# =====================================================================

class OrderAdmin(ModelView, model=Order):
    name = "Заказ"
    name_plural = "Заказы"
    icon = "fa-solid fa-cart-shopping"

    column_list = ["id", "order_id", "campaign_id", "status", "code_value", "total_amount", "created_at", "delivered_at"]
    column_details_list = ["id", "order_id", "campaign_id", "customer_id", "status", "total_amount", "currency", "code_id", "code_value", "created_at", "delivered_at"]

    column_searchable_list = ["order_id", "code_value", "campaign_id", "customer_id"]
    column_filters = ["status", "campaign_id"]
    column_default_sort = ("created_at", True)  # 🔥 СТРОКА, а не Order.created_at
    page_size = 25

    can_create = False
    can_edit = False
    can_delete = False


class ChatAdmin(ModelView, model=Chat):
    name = "Чат"
    name_plural = "Чаты"
    icon = "fa-solid fa-comments"

    column_list = ["id", "yandex_chat_id", "crm_marketplace_name", "customer_name", "platform", "is_active", "last_activity"]
    column_details_list = ["id", "yandex_campaign_id", "crm_marketplace_name", "yandex_chat_id", "external_chat_id", "crm_chat_id", "customer_name", "product_name", "platform", "is_active", "is_priority", "last_activity"]

    column_searchable_list = ["yandex_chat_id", "customer_name", "crm_marketplace_name", "external_chat_id"]
    column_filters = ["crm_marketplace_name", "platform", "is_active"]
    column_default_sort = ("last_activity", True)  # 🔥 СТРОКА
    page_size = 25

    can_create = False
    can_edit = False
    can_delete = False


class ChatMessageAdmin(ModelView, model=ChatMessage):
    name = "Сообщение"
    name_plural = "Сообщения"
    icon = "fa-solid fa-message"

    column_list = ["id", "chat_id", "sender", "status", "yandex_message_id", "created_at"]
    column_details_list = ["id", "chat_id", "sender", "text", "yandex_message_id", "status", "error_message", "created_at"]

    column_searchable_list = ["yandex_message_id", "external_message_id"]
    column_filters = ["sender", "status"]
    column_default_sort = ("created_at", True)  # 🔥 СТРОКА
    page_size = 50

    can_create = False
    can_edit = False
    can_delete = False


class CatalogItemAdmin(ModelView, model=CatalogItem):
    name = "Товар"
    name_plural = "Товары"
    icon = "fa-solid fa-box"

    column_list = ["id", "channel_id", "channel_slot_id", "product_name", "publish", "withdraw", "target_amount", "updated_at"]
    column_details_list = ["id", "channel_id", "channel_slot_id", "sellable_position_id", "product_name", "product_variant_name", "publish", "withdraw", "target_amount", "target_currency", "presentation_title", "updated_at"]

    column_searchable_list = ["product_name", "product_variant_name"]
    column_filters = ["channel_id", "publish", "withdraw"]
    column_default_sort = ("updated_at", True)  # 🔥 СТРОКА
    page_size = 50

    can_create = False
    can_edit = False
    can_delete = False


class ListingAdmin(ModelView, model=Listing):
    name = "Объявление"
    name_plural = "Объявления"
    icon = "fa-solid fa-store"

    column_list = ["id", "external_id", "channel_id", "status", "reported_price_amount", "consecutive_error_count", "updated_at"]
    column_details_list = ["id", "external_id", "channel_id", "status", "reported_price_amount", "reported_price_currency", "presentation_title", "last_error_text", "consecutive_error_count", "updated_at"]

    column_searchable_list = ["external_id"]
    column_filters = ["channel_id", "status"]
    column_default_sort = ("updated_at", True)  # 🔥 СТРОКА
    page_size = 50

    can_create = False
    can_edit = False
    can_delete = False


class SyncStateAdmin(ModelView, model=SyncState):
    name = "Синхронизация"
    name_plural = "Синхронизации"
    icon = "fa-solid fa-arrows-rotate"

    column_list = ["id", "channel_id", "module_declaration_revision", "executor_state_revision", "last_sync_at"]
    column_details_list = ["id", "channel_id", "next_cursor", "module_declaration_revision", "executor_state_revision", "last_sync_at", "created_at"]

    column_searchable_list = []
    column_filters = ["channel_id"]
    column_default_sort = ("last_sync_at", True)  # 🔥 СТРОКА (Именно здесь была ошибка!)
    page_size = 25

    can_create = False
    can_edit = False
    can_delete = False

class WebhookLogAdmin(ModelView, model=WebhookLog):
    name = "Вебхук"
    name_plural = "Журнал вебхуков"
    icon = "fa-solid fa-bolt"

    column_list = [
        WebhookLog.id,
        WebhookLog.webhook_type,
        WebhookLog.campaign_id,
        WebhookLog.order_id,
        WebhookLog.status,
        WebhookLog.signature_valid,
        WebhookLog.created_at,
    ]

    column_details_list = [
        WebhookLog.id,
        WebhookLog.webhook_type,
        WebhookLog.campaign_id,
        WebhookLog.order_id,
        WebhookLog.signature_valid,
        WebhookLog.status,
        WebhookLog.error_message,
        WebhookLog.payload,
        WebhookLog.created_at,
    ]

    column_searchable_list = [WebhookLog.order_id, WebhookLog.campaign_id, WebhookLog.webhook_type]
    column_filters = [WebhookLog.webhook_type, WebhookLog.status, WebhookLog.signature_valid]
    column_default_sort = (WebhookLog.created_at, True)
    page_size = 50

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
    admin.add_view(WebhookLogAdmin)

    return admin
