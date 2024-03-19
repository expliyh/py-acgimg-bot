import logging

from fastapi import FastAPI, Request

from telegram import Update, Bot
from telegram.ext import Application, CallbackContext, CommandHandler

app = FastAPI()

tg_ready = False

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def start(update: Update, context) -> None:
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello!")


# TELEGRAM_TOKEN = 'AAAA'

bot: Bot | None = None

tg_app: Application | None = None


# tg_app.add_handler(CommandHandler("start", start))


@app.on_event("startup")
async def startup() -> None:
    from registries import create_tables, config_registry
    create_tables()
    global tg_ready
    tokens = await config_registry.get_bot_tokens()
    if len(tokens) > 1:
        raise Exception("Too many bot tokens, Multiple bot tokens are currently not supported")
    if len(tokens) == 0:
        raise Exception("No bot token found")
    token = tokens[0]
    global bot
    bot = Bot(token.token)
    global tg_app
    tg_app = Application.builder().token(token.token).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_ready = True


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}


@app.post("/tapi/")
async def telegram_webhook(request: Request):
    if not tg_ready:
        return

    update = Update.de_json(await request.json(), bot)

    await tg_app.update_queue.put(update)

    return {'ok': True}
