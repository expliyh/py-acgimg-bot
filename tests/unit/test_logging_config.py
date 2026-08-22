import json
import logging
from datetime import datetime

from utils.logging_config import JsonFormatter, setup_logging


def test_json_log_format_serializes_core_record_fields() -> None:
    record = logging.LogRecord(
        name="test.logger",
        level=logging.WARNING,
        pathname=__file__,
        lineno=42,
        msg="Something happened: %s",
        args=("now",),
        exc_info=None,
    )

    formatter = JsonFormatter(datefmt="%Y-%m-%d")
    payload = json.loads(formatter.format(record))

    assert payload == {
        "timestamp": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d"),
        "level": "WARNING",
        "logger": "test.logger",
        "line": 42,
        "message": "Something happened: now",
    }


def test_setup_logging_treats_json_as_a_formatter_mode(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def capture_config(config: dict[str, object]) -> None:
        captured.update(config)

    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setattr("logging.config.dictConfig", capture_config)

    setup_logging(force=True)

    formatters = captured["formatters"]
    assert isinstance(formatters, dict)
    assert formatters["detailed"] == {
        "()": "utils.logging_config.JsonFormatter",
        "datefmt": "%Y-%m-%d %H:%M:%S",
    }
