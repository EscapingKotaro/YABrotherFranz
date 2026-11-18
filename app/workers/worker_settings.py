import logging
from arq.connections import RedisSettings
from urllib.parse import urlparse

# 🔥 ЖЕСТКАЯ НАСТРОЙКА ЛОГОВ (ДОЛЖНА БЫТЬ ПЕРВОЙ!)
# force=True перезаписывает настройки по умолчанию, которые ставит ARQ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True
)

# Теперь импортируем наши модули (они подхватят эту настройку)
from app.config import settings
#from app.workers.catalog_tasks import sync_catalog_task, process_removal_requests_task
from app.workers.chat_tasks import poll_crm_tasks
from app.workers.order_tasks import process_order_task

# Парсим REDIS_URL из .env
parsed = urlparse(settings.redis_url)

redis_settings = RedisSettings(
    host=parsed.hostname or "redis",
    port=parsed.port or 6379,
    database=int(parsed.path.lstrip('/') or 0),
    password=parsed.password,
)

WORKER_FUNCTIONS = [
  #  sync_catalog_task,
  #  process_removal_requests_task,
    poll_crm_tasks,
    process_order_task,
]

class WorkerSettings:
    functions = WORKER_FUNCTIONS
    redis_settings = redis_settings
    job_timeout = 300
    retry_jobs = True
    max_tries = 3
    health_check_interval = 10
