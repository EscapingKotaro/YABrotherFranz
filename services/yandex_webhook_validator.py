# app/services/yandex_webhook_validator.py
import hmac
import hashlib
import logging
from fastapi import HTTPException, status
from app.config import settings

logger = logging.getLogger(__name__)


class YandexWebhookValidator:
    """Проверка подписи вебхуков от Яндекс Маркета"""
    
    @staticmethod
    def validate_signature(payload: bytes, signature: str, campaign_id: str) -> bool:
        """
        Проверяет HMAC-SHA256 подпись webhook payload.
        Секрет берется из конфига по campaign_id.
        """
        account = settings.accounts_by_campaign.get(campaign_id)
        if not account:
            logger.warning(f"[WebhookValidator] Unknown campaign_id: {campaign_id}")
            return False
        
        if not account.webhook_secret:
            # Если секрет не настроен, пропускаем проверку (для dev)
            logger.warning(f"[WebhookValidator] No webhook_secret for campaign {campaign_id}, skipping validation")
            return True
        
        expected_signature = hmac.new(
            key=account.webhook_secret.encode('utf-8'),
            msg=payload,
            digestmod=hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected_signature, signature)
    
    @classmethod
    def validate(cls, payload: bytes, signature: str | None, campaign_id: str):
        """Валидирует подпись или кидает 401"""
        if not signature:
            # Если подпись не передана, но секрет настроен — это ошибка
            account = settings.accounts_by_campaign.get(campaign_id)
            if account and account.webhook_secret:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing signature header"
                )
            # Если секрет не настроен — пропускаем (для dev)
            return
        
        if not cls.validate_signature(payload, signature, campaign_id):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid signature"
            )