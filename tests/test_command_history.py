from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services import command_history


def test_safe_truncate():
    assert command_history._safe_truncate(None) is None
    assert command_history._safe_truncate("short", 10) == "short"
    assert command_history._safe_truncate("abcdef", 4) == "abc…"


@pytest.mark.asyncio
async def test_command_logger_records_success(monkeypatch):
    record = AsyncMock()
    monkeypatch.setattr(command_history.command_history_registry, "record_command_execution", record)
    update = SimpleNamespace(
        effective_message=SimpleNamespace(text="/ping one", message_id=7),
        effective_chat=SimpleNamespace(id=-10, type="group"),
        effective_user=SimpleNamespace(id=20),
    )
    context = SimpleNamespace(args=["one"])

    @command_history.command_logger("ping")
    async def handler(update, context):
        return "pong"

    assert handler.__command_name__ == "ping"
    assert await handler(update, context) == "pong"
    values = record.await_args.kwargs
    assert values["duration_ms"] >= 0
    assert values["triggered_at"].tzinfo is not None
    assert values["command"] == "ping"
    assert values["user_id"] == 20
    assert values["chat_id"] == -10
    assert values["arguments"] == ["one"]
    assert values["success"] is True
    assert values["error_message"] is None


@pytest.mark.asyncio
async def test_command_logger_reraises_and_records_failure(monkeypatch):
    record = AsyncMock()
    monkeypatch.setattr(command_history.command_history_registry, "record_command_execution", record)
    update = SimpleNamespace(effective_message=None, effective_chat=None, effective_user=None)

    @command_history.command_logger("fail")
    async def handler(update, context):
        raise RuntimeError("x" * 600)

    with pytest.raises(RuntimeError):
        await handler(update, SimpleNamespace())
    values = record.await_args.kwargs
    assert values["success"] is False
    assert values["user_id"] is None
    assert values["raw_text"] is None
    assert len(values["error_message"]) == 500
    assert values["error_message"].endswith("…")
