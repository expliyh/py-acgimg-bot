import asyncio
import logging

from fastapi import FastAPI, Request

from telegram import Update, Bot

import bot
from bot import tg_bot

from contextlib import asynccontextmanager
from registries import engine, config_registry
import uvicorn

from configs import config
from services import pixiv, storage_service
from services.storage_service import backblaze

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
    await engine.create_all()
    storage = await storage_service.use()
    if storage is None:
        logger.warning("No storage service set")
    else:
        await storage.get_config()
    await tg_bot.config()
    await pixiv.read_token_from_config()
    pixiv.token_refresh()
    logger.warning("Bot started")
    yield
    pass


app = FastAPI(lifespan=lifespan)


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

# if __name__ == "__main__":
#     uvicorn.run("main:app", host="0.0.0.0", port=8000)
