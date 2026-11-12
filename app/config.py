from pydantic_settings import BaseSettings
from pydantic import BaseModel, Field
from typing import List
import json
import os

class YandexAccountConfig(BaseModel):
    campaign_id: str = Field(..., description="ID кампании в Яндекс Маркете")
    business_id: str = Field(..., description="ID бизнеса")
    api_key: str = Field(..., description="Api-Key для этого ЛК")
    crm_marketplace_name: str = Field(..., description="Как этот ЛК называется в CRM")
    webhook_secret: str = Field(default="", description="Секрет для проверки подписи вебхуков")

class Settings(BaseSettings):
    # === Базовые настройки ===
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/yandex_client"
    redis_url: str = "redis://localhost:6379/0"
    
    # === Тестовый режим ===
    enable_mock_mode: bool = False
    mock_cndk: bool = True
    mock_yandex: bool = True
    mock_code_api: bool = True
    mock_crm: bool = True  
    
    # === CNDK Posting API ===
    cndk_api_url: str = "https://sandbox.auto-posting.cyndykshop.su"
    cndk_api_key: str = ""
    
    # === Code API ===
    code_api_url: str = "https://ps.cyndykshop.su"
    code_api_app_key: str = ""
    code_api_app_secret: str = ""
    
    # === CRM API (🔥 НОВОЕ) ===
    crm_api_url: str = "https://chats.systemseller.net"
    crm_api_key: str = ""  # API-ключ для авторизации в CRM
    crm_polling_interval: int = 5  # Интервал опроса CRM на наличие задач (сек)
    crm_batch_size: int = 50  # Максимум задач за один запрос
    
    # === Яндекс Маркет (мульти-аккаунтность) ===
    yandex_accounts_json: str = "[]"
    
    @property
    def yandex_accounts(self) -> List[YandexAccountConfig]:
        return [YandexAccountConfig(**acc) for acc in json.loads(self.yandex_accounts_json)]
    
    @property
    def accounts_by_campaign(self) -> dict[str, YandexAccountConfig]:
        return {acc.campaign_id: acc for acc in self.yandex_accounts}
    
    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()