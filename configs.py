import os

from dotenv import load_dotenv


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


db_config_declare = {
    'allow_r18g': False,
    'enable_on_new_group': False,
    'pixiv_cache_to_telegram': True,
    'super_user': '1285315854',
}


class __Config:
    def __init__(self):
        load_dotenv()
        # 数据库类型: 'sqlite'（默认，无需任何配置）或 'mysql'/'mariadb'
        self.db_type = (os.getenv('DATABASE_TYPE') or 'sqlite').strip().lower()
        self.db_host = os.getenv('DATABASE_HOST') or 'localhost'
        self.db_port = int(os.getenv('DATABASE_PORT') or 3306)
        self.db_username = os.getenv('DATABASE_USERNAME') or 'root'
        self.db_password = os.getenv('DATABASE_PASSWORD') or ''
        self.db_name = os.getenv('DATABASE_NAME') or 'acgimg'
        self.db_prefix = os.getenv('DATABASE_PREFIX') or ''
        self.external_url = os.getenv('EXTERNAL_URL')
        self.telegram_webhook_secret = os.getenv('TELEGRAM_WEBHOOK_SECRET') or None

        # Timeouts are seconds. python-telegram-bot uses a separate HTTP client for
        # getUpdates, and it adds telegram_polling_timeout to the getUpdates read
        # timeout, so telegram_get_updates_read_timeout is only the extra margin.
        self.telegram_connect_timeout = _env_float('TELEGRAM_CONNECT_TIMEOUT', 10.0)
        self.telegram_read_timeout = _env_float('TELEGRAM_READ_TIMEOUT', 20.0)
        self.telegram_write_timeout = _env_float('TELEGRAM_WRITE_TIMEOUT', 20.0)
        self.telegram_pool_timeout = _env_float('TELEGRAM_POOL_TIMEOUT', 5.0)
        self.telegram_media_write_timeout = _env_float('TELEGRAM_MEDIA_WRITE_TIMEOUT', 60.0)
        self.telegram_get_updates_connect_timeout = _env_float(
            'TELEGRAM_GET_UPDATES_CONNECT_TIMEOUT', 10.0
        )
        self.telegram_get_updates_read_timeout = _env_float(
            'TELEGRAM_GET_UPDATES_READ_TIMEOUT', 15.0
        )
        self.telegram_get_updates_write_timeout = _env_float(
            'TELEGRAM_GET_UPDATES_WRITE_TIMEOUT', 10.0
        )
        self.telegram_get_updates_pool_timeout = _env_float(
            'TELEGRAM_GET_UPDATES_POOL_TIMEOUT', 5.0
        )
        self.telegram_polling_timeout = _env_float('TELEGRAM_POLLING_TIMEOUT', 10.0)
        # Extra seconds after the httpx timeouts. The asyncio deadline cancels a
        # request whose socket timeout never fires (dead proxy, unacked send).
        self.telegram_request_hard_slack = _env_float('TELEGRAM_REQUEST_HARD_SLACK', 5.0)
        self.telegram_retry_attempts = _env_int('TELEGRAM_RETRY_ATTEMPTS', 3)
        self.telegram_retry_initial_delay = _env_float('TELEGRAM_RETRY_INITIAL_DELAY', 1.0)
        self.telegram_retry_backoff = _env_float('TELEGRAM_RETRY_BACKOFF', 2.0)
        self.telegram_retry_max_delay = _env_float('TELEGRAM_RETRY_MAX_DELAY', 30.0)
        # Retries inside python-telegram-bot's polling/webhook bootstrap. 0 disables
        # them. Values below 0 are treated as 0 so one config() call cannot retry forever.
        self.telegram_bootstrap_retries = _env_int('TELEGRAM_BOOTSTRAP_RETRIES', 2)
        self.telegram_shutdown_timeout = _env_float('TELEGRAM_SHUTDOWN_TIMEOUT', 15.0)
        self.telegram_watchdog_interval = _env_float('TELEGRAM_WATCHDOG_INTERVAL', 30.0)
        # Floor is two full getUpdates budgets, so a healthy long poll is not a stall.
        self.telegram_poll_stall_timeout = _env_float('TELEGRAM_POLL_STALL_TIMEOUT', 120.0)
        self.telegram_healthcheck_failures = _env_int('TELEGRAM_HEALTHCHECK_FAILURES', 3)
        self.telegram_tcp_keepidle = _env_int('TELEGRAM_TCP_KEEPIDLE', 30)
        self.telegram_tcp_keepintvl = _env_int('TELEGRAM_TCP_KEEPINTVL', 10)
        self.telegram_tcp_keepcnt = _env_int('TELEGRAM_TCP_KEEPCNT', 3)
        # How long unacknowledged TCP payload may sit before the kernel aborts the socket.
        self.telegram_tcp_user_timeout = _env_float('TELEGRAM_TCP_USER_TIMEOUT', 20.0)


config = __Config()
