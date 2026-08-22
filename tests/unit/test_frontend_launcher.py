"""Regression tests for the frontend auto-start decision."""

from utils import frontend_launcher


def test_debug_log_level_starts_dev_server_when_a_static_build_exists(monkeypatch):
    """An explicit Uvicorn debug log level selects Vite over the static build."""
    monkeypatch.delenv("AUTO_START_FRONTEND", raising=False)

    should_start = getattr(frontend_launcher, "should_start_frontend_dev_server", None)

    assert should_start is not None
    assert should_start(
        static_build_exists=True,
        argv=["uvicorn", "main:app", "--log-level", "debug"],
    )


def test_explicit_disable_overrides_debug_log_level(monkeypatch):
    monkeypatch.setenv("AUTO_START_FRONTEND", "0")

    should_start = getattr(frontend_launcher, "should_start_frontend_dev_server", None)

    assert should_start is not None
    assert not should_start(
        static_build_exists=True,
        argv=["uvicorn", "main:app", "--log-level=debug"],
    )
