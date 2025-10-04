import asyncio
import logging

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from telegram import Update, Bot

import bot
from bot import tg_bot

from contextlib import asynccontextmanager
from registries import engine, config_registry
from routers import configs as config_routes, dashboard, groups, private, commands
import uvicorn

from configs import config, db_config_declare
from registries.config_registry import init_database_config
from services import pixiv, storage_service, schema_migrator

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# TELEGRAM_TOKEN = 'AAAA'


# tg_app.add_handler(CommandHandler("start", start))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tasks to run during application startup
    await engine.create_all()
    await schema_migrator.ensure_schema_migrations(engine.engine)
    await storage_service.ensure_storage_config_defaults()
    storage = await storage_service.use()
    if storage is None:
        logger.warning("No storage service set")
    else:
        await storage.get_config()
    await tg_bot.config()
    await pixiv.read_token_from_config()
    if pixiv.enabled:
        await pixiv.token_refresh()
    else:
        logger.warning("Pixiv features disabled due to missing token")

    # Initialize database configuration defaults
    try:
        await init_database_config(db_config_declare)
        logger.info("Database configurations initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database configurations: {e}")

    logger.warning("Bot started")
    yield

    # Tasks to run during application shutdown
    pass


app = FastAPI(lifespan=lifespan)

for router in (
    dashboard.router,
    groups.router,
    private.router,
    config_routes.router,
    commands.router,
):
    app.include_router(router)

webui_dir = Path(__file__).parent / "webui"
dist_dir = webui_dir / "dist"
static_source: Path | None = None

if dist_dir.exists():
    static_source = dist_dir
elif webui_dir.exists():
    static_source = webui_dir

if static_source:
    app.mount("/admin", StaticFiles(directory=static_source, html=True), name="admin")


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}


@app.post("/tapi/")
async def telegram_webhook(request: Request):
    await tg_bot.put_update(request)

    return {'ok': True}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
