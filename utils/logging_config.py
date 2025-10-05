import logging
import logging.config
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_DEFAULT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
_DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    return normalized in {"1", "true", "yes", "on", "y"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def setup_logging(force: bool = False) -> None:
    """Configure application logging with console and optional rotating file handlers."""

    root_logger = logging.getLogger()
    if root_logger.handlers and not force:
        return

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format = os.getenv("LOG_FORMAT", _DEFAULT_FORMAT)
    date_format = os.getenv("LOG_DATE_FORMAT", _DEFAULT_DATE_FORMAT)

    log_to_file = _env_bool("LOG_TO_FILE", False)
    log_file = os.getenv("LOG_FILE", "logs/app.log")
    max_bytes = _env_int("LOG_MAX_BYTES", 5 * 1024 * 1024)
    backup_count = _env_int("LOG_BACKUP_COUNT", 5)

    handlers: dict[str, Mapping[str, Any] | dict[str, Any]] = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "detailed",
            "stream": "ext://sys.stdout",
        }
    }

    root_handler_names = ["console"]

    if log_to_file:
        log_path = Path(log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "detailed",
            "filename": str(log_path),
            "maxBytes": max_bytes,
            "backupCount": backup_count,
            "encoding": "utf-8",
        }
        root_handler_names.append("file")

    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "detailed": {
                "format": log_format,
                "datefmt": date_format,
            }
        },
        "handlers": handlers,
        "root": {
            "level": log_level,
            "handlers": root_handler_names,
        },
        "loggers": {
            "httpx": {
                "level": "WARNING",
                "propagate": False,
                "handlers": root_handler_names,
            },
            "uvicorn": {
                "level": "INFO",
                "propagate": False,
                "handlers": root_handler_names,
            },
            "uvicorn.error": {
                "level": "INFO",
                "propagate": False,
                "handlers": root_handler_names,
            },
            "uvicorn.access": {
                "level": os.getenv("UVICORN_ACCESS_LOG_LEVEL", "INFO"),
                "propagate": False,
                "handlers": root_handler_names,
            },
        },
    }

    logging.config.dictConfig(config)
    logging.captureWarnings(True)


__all__ = ["setup_logging"]
