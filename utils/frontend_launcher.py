"""Auto-start the Vite dev server when the backend boots (development convenience).

Disabled by setting ``AUTO_START_FRONTEND=0`` in the environment.
"""

import asyncio
import logging
import os
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# The dev server prints non-GBK characters (➜, —, ANSI color codes). Reconfigure
# the console streams to UTF-8 with lossy replacement so log forwarding never
# raises UnicodeEncodeError on Windows (GBK default).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

#: Handle to the spawned Vite dev server process, if any.
_dev_server: asyncio.subprocess.Process | None = None

WEBUI_DIR = Path(__file__).resolve().parent.parent / "webui"
DEFAULT_PORT = 5173


def auto_start_enabled() -> bool:
    value = (os.getenv("AUTO_START_FRONTEND") or "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _build_command() -> list[str]:
    """Return the command that runs ``npm run dev`` in the webui directory."""
    if sys.platform == "win32":
        # .cmd files cannot be executed directly via CreateProcess, wrap with cmd.exe
        return ["cmd", "/c", "npm run dev"]
    return ["npm", "run", "dev"]


async def start_frontend_dev_server() -> bool:
    """Spawn ``npm run dev`` for the webui directory.

    Returns True when the dev server process was started (or already running),
    False when it could not be started (npm missing, webui missing, ...).
    Does not block on the long-running Vite process.
    """
    global _dev_server

    if _dev_server is not None and _dev_server.returncode is None:
        return True

    if not WEBUI_DIR.is_dir():
        logger.warning("Frontend directory not found at %s; skipping dev server", WEBUI_DIR)
        return False

    command = _build_command()
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(WEBUI_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        logger.warning(
            "npm not found; cannot auto-start the frontend dev server "
            "(install Node.js or set AUTO_START_FRONTEND=0)"
        )
        return False
    except Exception:
        logger.exception("Failed to start the frontend dev server")
        return False

    _dev_server = proc
    logger.info(
        "Started frontend dev server (pid=%s) — open http://localhost:%s/admin/",
        proc.pid,
        DEFAULT_PORT,
    )
    asyncio.create_task(_pump_output(proc))
    asyncio.create_task(_watch_startup(proc))
    return True


async def _pump_output(proc: asyncio.subprocess.Process) -> None:
    """Forward the dev server's output into the backend log."""
    assert proc.stdout is not None
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            logger.info("frontend: %s", _ANSI_RE.sub("", line.decode(errors="replace")).strip())
    except (asyncio.CancelledError, RuntimeError):
        pass


async def _watch_startup(proc: asyncio.subprocess.Process) -> None:
    """Detect an early exit of the dev server (e.g. npm error) and log it."""
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        return  # still running after 5s — assume healthy
    if proc.returncode != 0:
        logger.warning(
            "Frontend dev server exited early with code %s "
            "(is port %s in use? run `npm install` inside webui/)",
            proc.returncode,
            DEFAULT_PORT,
        )


async def stop_frontend_dev_server() -> None:
    """Terminate the dev server process tree if it is still running."""
    global _dev_server

    proc = _dev_server
    if proc is None:
        return
    _dev_server = None

    if proc.returncode is not None:
        return

    logger.info("Stopping frontend dev server (pid=%s)", proc.pid)
    if sys.platform == "win32":
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(proc.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
        except Exception:
            logger.exception("taskkill failed; falling back to terminate()")
            proc.terminate()
    else:
        proc.terminate()

    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        proc.kill()
