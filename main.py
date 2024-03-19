import logging

from fastapi import FastAPI, Request

from telegram import Update, Bot
from telegram.ext import Application, CallbackContext, CommandHandler

from contextlib import asynccontextmanager
from registries import engine, config_registry

from configs import config

tg_ready = False

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def start(update: Update, context) -> None:
    logger.info(f"Update START for user: {update.effective_user}")
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello!")


# TELEGRAM_TOKEN = 'AAAA'

bot: Bot | None = None

tg_app: Application | None = None


# tg_app.add_handler(CommandHandler("start", start))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await engine.create_all()
    global tg_ready
    tokens = await config_registry.get_bot_tokens()
    if len(tokens) > 1:
        raise Exception("Too many bot tokens, Multiple bot tokens are currently not supported")
    if len(tokens) == 0:
        raise Exception("No bot token found")
    token = tokens[0]
    global bot
    bot = Bot(token.token)
    await bot.set_webhook(f"https://{config.external_url}/tapi/")
    global tg_app
    tg_app = Application.builder().token(token.token).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_ready = True
    logger.warning("Bot started")
    yield
    pass


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    if not tg_ready:
        logger.warning("BOT NOT READY")
        logger.warning(tg_app)
        return
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}


@app.post("/tapi/")
async def telegram_webhook(request: Request):
    if not tg_ready:
        logger.warning("BOT NOT READY")
        logger.warning(tg_app)
        return

    update = Update.de_json(await request.json(), bot)

    await tg_app.update_queue.put(update)

    return {'ok': True}
