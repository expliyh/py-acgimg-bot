"""Shared fixtures for the test suite.

- All tests run against an isolated temporary SQLite database (the real
  ``storage/acgimg.db`` is never touched).
- Every test starts with a freshly created schema.
- ``client`` provides a FastAPI TestClient (lifespan included).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the project root importable regardless of the working directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session", autouse=True)
def _isolated_database(tmp_path_factory):
    """Point the engine at a temporary SQLite file for the whole session."""
    import importlib

    db_path = tmp_path_factory.mktemp("db") / "test.db"

    # registries.engine 属性已被 __init__ 导出为 Engine 实例，需取真实模块
    engine_module = importlib.import_module("registries.engine")

    original_build = engine_module._build_db_url
    engine_module._build_db_url = lambda: f"sqlite+aiosqlite:///{db_path.as_posix()}"
    yield
    engine_module._build_db_url = original_build


@pytest.fixture(autouse=True)
async def _fresh_database():
    """Recreate all tables before each test."""
    from models import Base
    from registries import engine

    await engine.create_all()
    async with engine.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.engine.dispose()


@pytest.fixture()
def client():
    """FastAPI TestClient with a full lifespan (real HTTP layer via ASGI)."""
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture()
def pixiv_disabled(monkeypatch):
    """Force the Pixiv service into a known disabled state."""
    from services import pixiv

    monkeypatch.setattr(pixiv, "enabled", False)
    return pixiv


@pytest.fixture()
def pixiv_enabled(monkeypatch):
    """Force the Pixiv service into a known enabled state."""
    from services import pixiv

    monkeypatch.setattr(pixiv, "enabled", True)
    return pixiv
