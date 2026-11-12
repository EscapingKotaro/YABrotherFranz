# app/workers/worker_settings.py
from arq.connections import RedisSettings
from app.config import settings

# Настройки Redis для ARQ
parsed = urlparse(settings.redis_url)

redis_settings = RedisSettings(
    host=parsed.hostname or "redis",
    port=parsed.port or 6379,
    database=int(parsed.path.lstrip('/') or 0),
    password=parsed.password,
)

# Функции, которые будут выполняться воркерами
# Импортируем здесь, чтобы ARQ мог их найти
from app.workers.catalog_tasks import sync_catalog_task, process_removal_requests_task
from app.workers.chat_tasks import poll_crm_tasks
from app.workers.order_tasks import process_order_task

# Список всех задач
WORKER_FUNCTIONS = [
    sync_catalog_task,
    process_removal_requests_task,
    poll_crm_tasks,
    process_order_task,
]

# Настройки воркера (используются при запуске `arq app.workers.worker_settings.WorkerSettings`)
class WorkerSettings:
    functions = WORKER_FUNCTIONS
    redis_settings = redis_settings
    
    # Таймауты и retry
    job_timeout = 300  # 5 минут
    retry_jobs = True
    max_tries = 3
    
    # Health check
    health_check_interval = 10