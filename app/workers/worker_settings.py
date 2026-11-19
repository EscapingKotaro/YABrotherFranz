# app/workers/worker_settings.py
import logging
import os
from arq.connections import RedisSettings
from urllib.parse import urlparse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True
)

from app.config import settings

# Импортируем все задачи
from app.workers.catalog_tasks import sync_catalog_task, process_removal_requests_task
from app.workers.chat_tasks import poll_crm_tasks
from app.workers.order_tasks import process_order_task

parsed = urlparse(settings.redis_url)
redis_settings = RedisSettings(
    host=parsed.hostname or "redis",
    port=parsed.port or 6379,
    database=int(parsed.path.lstrip('/') or 0),
    password=parsed.password,
)

# 🔥 РАЗДЕЛЕНИЕ ЗАДАЧ ПО РОЛЯМ
worker_role = os.getenv("WORKER_ROLE", "all").lower()

if worker_role == "catalog":
    WORKER_FUNCTIONS = [sync_catalog_task, process_removal_requests_task]
elif worker_role == "chat":
    WORKER_FUNCTIONS = [poll_crm_tasks]
elif worker_role == "fulfillment":
    WORKER_FUNCTIONS = [process_order_task]
else:
    # Fallback для старых настроек
    WORKER_FUNCTIONS = [sync_catalog_task, process_removal_requests_task, poll_crm_tasks, process_order_task]

class WorkerSettings:
    functions = WORKER_FUNCTIONS
    redis_settings = redis_settings
    job_timeout = 300
    retry_jobs = True
    max_tries = 3
    health_check_interval = 10
