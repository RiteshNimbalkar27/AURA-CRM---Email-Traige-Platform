"""
AURA ARQ Worker Entrypoint

Start with:
    arq app.worker.main.WorkerSettings

On Windows, run from the backend/ directory with the venv activated.
ARQ uses a SelectorEventLoop internally, so no special event loop policy is needed.
"""
import logging
import sys

# Windows: use SelectorEventLoop for psycopg3/asyncpg compatibility
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from arq import cron
from arq.connections import RedisSettings

from app.config import get_settings
from app.worker.tasks import classify_message_task  # noqa: F401  (registers task)

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# Parse Redis URL → arq RedisSettings
# ---------------------------------------------------------------------------

def _parse_redis_settings() -> RedisSettings:
    """Convert settings.redis_url string to arq RedisSettings."""
    return RedisSettings.from_dsn(settings.redis_url)


# ---------------------------------------------------------------------------
# Worker Configuration
# ---------------------------------------------------------------------------

class WorkerSettings:
    """ARQ WorkerSettings class — consumed by `arq app.worker.main.WorkerSettings`."""

    # Registered task functions
    functions = [classify_message_task]

    # Redis connection
    redis_settings = _parse_redis_settings()

    # Retry configuration
    max_jobs = 10           # max concurrent jobs
    job_timeout = 300       # 5-minute max per job
    max_tries = 3           # retry up to 3 times on failure
    retry_failed_jobs = True

    # Health
    health_check_interval = 30  # seconds

    # Logging
    log_results = True

    on_startup = None
    on_shutdown = None
