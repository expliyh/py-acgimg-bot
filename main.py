from fastapi import FastAPI, Request

from telegram import Update, Bot
from telegram.ext import Application, CallbackContext, CommandHandler

app = FastAPI()


async def start(update: Update, context) -> None:
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello!")


TELEGRAM_TOKEN = 'AAAA'

bot = Bot(token=TELEGRAM_TOKEN)

tg_app = Application.builder().token(TELEGRAM_TOKEN).build()

tg_app.add_handler(CommandHandler("start", start))


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}


@app.post("/tapi/")
async def telegram_webhook(request: Request):
    update = Update.de_json(await request.json(), bot)

    await tg_app.update_queue.put(update)

    return {'ok': True}

