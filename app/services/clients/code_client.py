# app/services/clients/code_client.py
import logging
import random
import string
from typing import Optional

import httpx

from app.config import settings
from app.core.retry import retry_with_backoff

logger = logging.getLogger(__name__)


class RealCodeApiClient:
    """
    Реальный клиент для работы с Code API.
    Выпуск кодов активации для заказов.
    """
    
    def __init__(self):
        self.base_url = settings.code_api_url.rstrip("/")
        self.app_key = settings.code_api_app_key
        self.app_secret = settings.code_api_app_secret
        
        # HTTP/2 клиент с Basic Auth
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
            auth=httpx.BasicAuth(username=self.app_key, password=self.app_secret),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
    
    @retry_with_backoff(max_retries=3, base_delay=2)
    async def can_activate(
        self,
        game_name: str,
        platform: str,
        method: str = "P2",
        limit: int = 20,
    ) -> dict:
        """
        Проверка возможности автовыдачи (без резервирования).
        
        Args:
            game_name: Название игры
            platform: Платформа (PlayStation, Nintendo, Xbox, Steam, Other)
            method: Метод активации (P2, P3, Normal, Prem)
            limit: Максимум кандидатов в ответе
        
        Returns:
            {
                "canActivate": bool,
                "reason": str,
                "accounts": [...],
                "accountsReturned": int,
                "hasMore": bool
            }
        """
        url = "/api/code/CanActivate"
        payload = {
            "gameName": game_name,
            "platform": platform,
            "method": method,
            "limit": min(limit, 100),
        }
        
        logger.info(f"[CodeAPI] POST {url} | game={game_name}, platform={platform}, method={method}")
        
        response = await self.client.post(url, json=payload)
        
        # 422 означает, что платформа не поддерживает CanActivate (например, Xbox, Steam)
        if response.status_code == 422:
            logger.warning(f"[CodeAPI] CanActivate not supported for platform {platform}")
            return {"canActivate": True, "reason": "platform_does_not_support_check", "accountsReturned": 0}
        
        response.raise_for_status()
        result = response.json()
        
        can_activate = result.get("canActivate", False)
        reason = result.get("reason", "unknown")
        accounts_returned = result.get("accountsReturned", 0)
        
        logger.info(f"[CodeAPI] ✅ CanActivate: {can_activate}, reason={reason}, accounts={accounts_returned}")
        return result
    
    @retry_with_backoff(max_retries=5, base_delay=2)
    async def issue_code(
        self,
        marketplace: str,
        platform: str,
        game_name: str,
        task_number: str,
        method: Optional[str] = None,
        source_system_name: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> dict:
        """
        Выпуск кода активации (идемпотентно по taskNumber).
        
        Args:
            marketplace: Название площадки (Yandex, Ozon, Wildberries и т.д.)
            platform: Платформа (PlayStation, Nintendo, Xbox, Steam, Other)
            game_name: Название игры
            task_number: ID заказа (для идемпотентности)
            method: Метод активации (если None, Code API выберет по умолчанию)
            source_system_name: Источник (по умолчанию {marketplace}Client)
            client_id: ID клиента (email или nickname)
        
        Returns:
            {
                "issued": bool,
                "idempotent_replay": bool,
                "method": str,
                "code": {
                    "code": "ABCD-1234",
                    "status": "not_activated",
                    "game_title": str,
                    ...
                }
            }
        """
        url = "/api/code/Issue"
        
        payload = {
            "marketplace": marketplace,
            "platform": platform,
            "gameName": game_name,
            "taskNumber": task_number,
        }
        
        if method:
            payload["method"] = method
        if source_system_name:
            payload["sourceSystemName"] = source_system_name
        else:
            payload["sourceSystemName"] = f"{marketplace}Client"
        if client_id:
            payload["clientId"] = client_id
        
        logger.info(f"[CodeAPI] POST {url} | taskNumber={task_number}, game={game_name}, platform={platform}")
        
        response = await self.client.post(url, json=payload)
        response.raise_for_status()
        
        result = response.json()
        
        issued = result.get("issued", False)
        idempotent_replay = result.get("idempotent_replay", False)
        code_value = result.get("code", {}).get("code", "UNKNOWN")
        
        if idempotent_replay:
            logger.info(f"[CodeAPI] 🔄 Idempotent replay: returning existing code {code_value}")
        else:
            logger.info(f"[CodeAPI] ✅ Code issued: {code_value}")
        
        return result
    
    @retry_with_backoff(max_retries=3, base_delay=2)
    async def get_platforms(self, active_only: bool = True) -> dict:
        """
        Получить справочник платформ.
        
        Returns:
            {
                "items": [
                    {
                        "short_name": "PS",
                        "full_name": "PlayStation",
                        "issue_platform": "PlayStation",
                        "methods": ["P2", "P3", "Прямая покупка"],
                        "default_method": "P2"
                    },
                    ...
                ],
                "total": int
            }
        """
        url = "/api/code/GetPlatforms"
        params = {"activeOnly": str(active_only).lower()}
        
        logger.debug(f"[CodeAPI] GET {url} | activeOnly={active_only}")
        
        response = await self.client.get(url, params=params)
        response.raise_for_status()
        
        result = response.json()
        platforms_count = len(result.get("items", []))
        logger.info(f"[CodeAPI] ✅ Got {platforms_count} platforms")
        return result
    
    async def close(self):
        await self.client.aclose()


class MockCodeApiClient:
    """
    Мок-клиент для Code API (🔥 РЕЖИМ ЕБАША В КОНСОЛЬ).
    Эмулирует проверку склада и выпуск кодов.
    """
    
    def __init__(self):
        self._issued_codes = {}  # taskNumber -> code (для идемпотентности)
    
    async def can_activate(
        self,
        game_name: str,
        platform: str,
        method: str = "P2",
        limit: int = 20,
    ) -> dict:
        logger.info(f"[MOCK_CODE_API] POST /api/code/CanActivate | game={game_name}, platform={platform}, method={method}")
        logger.info("[MOCK_CODE_API] ✅ Проверка склада: Аккаунты доступны (canActivate=true)")
        
        return {
            "canActivate": True,
            "reason": "available",
            "accounts": [
                {
                    "accountId": "mock-account-1",
                    "accountNumber": "1234",
                    "login": "mock@example.com",
                    "gameName": game_name,
                }
            ],
            "accountsReturned": 1,
            "hasMore": False,
        }
    
    async def issue_code(
        self,
        marketplace: str,
        platform: str,
        game_name: str,
        task_number: str,
        method: Optional[str] = None,
        source_system_name: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> dict:
        logger.info(f"[MOCK_CODE_API] POST /api/code/Issue | taskNumber={task_number}, game={game_name}")
        
        # Идемпотентность: если уже выпускали код для этого taskNumber, возвращаем его
        if task_number in self._issued_codes:
            existing_code = self._issued_codes[task_number]
            logger.info(f"[MOCK_CODE_API] 🔄 Idempotent replay: returning existing code {existing_code}")
            return {
                "issued": True,
                "idempotent_replay": True,
                "method": method or "P2",
                "code": {
                    "code": existing_code,
                    "status": "not_activated",
                    "game_title": game_name,
                    "platform": platform,
                },
            }
        
        # Генерируем новый код
        mock_code = self._generate_mock_code(platform)
        self._issued_codes[task_number] = mock_code
        
        logger.info(f"[MOCK_CODE_API] 🎲 Генерирую и 'выдаю' код: {mock_code}")
        logger.info("[MOCK_CODE_API] ✅ Код успешно зарезервирован и выпущен (idempotent_replay=false)")
        
        return {
            "issued": True,
            "idempotent_replay": False,
            "method": method or "P2",
            "code": {
                "code": mock_code,
                "status": "not_activated",
                "game_title": game_name,
                "platform": platform,
                "activation_method": method or "P2",
            },
        }
    
    async def get_platforms(self, active_only: bool = True) -> dict:
        logger.info(f"[MOCK_CODE_API] GET /api/code/GetPlatforms | activeOnly={active_only}")
        logger.info("[MOCK_CODE_API] ✅ Returning mock platforms")
        
        return {
            "items": [
                {
                    "short_name": "PS",
                    "full_name": "PlayStation",
                    "issue_platform": "PlayStation",
                    "methods": ["P2", "P3", "Прямая покупка"],
                    "default_method": "P2",
                },
                {
                    "short_name": "NS",
                    "full_name": "Nintendo Switch",
                    "issue_platform": "Nintendo",
                    "methods": ["Normal", "Prem", "Прямая покупка"],
                    "default_method": "Normal",
                },
                {
                    "short_name": "XB",
                    "full_name": "Xbox",
                    "issue_platform": "Xbox",
                    "methods": ["Normal", "Prem", "Прямая покупка"],
                    "default_method": "Normal",
                },
            ],
            "total": 3,
        }
    
    def _generate_mock_code(self, platform: str) -> str:
        """Генерирует мок-код в формате ABCD-1234"""
        # Без I и O (чтобы не путать с 1 и 0)
        letters = ''.join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ", k=4))
        digits = ''.join(random.choices(string.digits, k=4))
        return f"{letters}-{digits}"
    
    async def close(self):
        logger.info("[MOCK_CODE_API] Client closed")