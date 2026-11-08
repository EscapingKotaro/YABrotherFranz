# app/services/clients/factory.py
from app.config import settings
from app.services.clients.crm_client import RealCrmClient, MockCrmClient
from app.services.clients.yandex_client import RealYandexClient, MockYandexClient
from app.services.clients.cndk_client import RealCndkClient, MockCndkClient
from app.services.clients.code_client import RealCodeApiClient, MockCodeApiClient


def get_crm_client():
    """Фабрика для получения CRM-клиента"""
    if settings.enable_mock_mode or settings.mock_crm:
        return MockCrmClient()
    return RealCrmClient()


def get_yandex_client():
    """Фабрика для получения Yandex-клиента"""
    if settings.enable_mock_mode or settings.mock_yandex:
        return MockYandexClient()
    return RealYandexClient()


def get_cndk_client():
    """Фабрика для получения CNDK-клиента"""
    if settings.enable_mock_mode or settings.mock_cndk:
        return MockCndkClient()
    return RealCndkClient()


def get_code_api_client():
    """Фабрика для получения Code API клиента"""
    if settings.enable_mock_mode or settings.mock_code_api:
        return MockCodeApiClient()
    return RealCodeApiClient()