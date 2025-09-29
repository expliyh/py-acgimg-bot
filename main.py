import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from telegram import Update, Bot

import bot
from bot import tg_bot

from contextlib import asynccontextmanager
from registries import engine, config_registry
import uvicorn

from configs import config, db_config_declare
from registries.config_registry import init_database_config
from services import pixiv, storage_service
from services.storage_service import backblaze
from services.admin_store import AdminStore
from routers import admin as admin_router

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
    # 应用启动时的逻辑
    await engine.create_all()
    storage = await storage_service.use()
    if storage is None:
        logger.warning("No storage service set")
    else:
        await storage.get_config()
    await tg_bot.config()
    await pixiv.read_token_from_config()
    pixiv.token_refresh()

    # 新增：初始化数据库配置
    try:
        await init_database_config(db_config_declare)
        logger.info("Database configurations initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database configurations: {e}")

    logger.warning("Bot started")

    # Pre-populate admin dashboard defaults when empty
    store: AdminStore = app.state.admin_store
    if not await store.list_groups():
        group = await store.create_group("主控群", "用于发布日常运营通知", ["核心", "公告"])
        await store.update_group(group.id, is_active=True)
    if not await store.list_private_chats():
        chat = await store.create_private_chat("@acg_fan", alias="联络员")
        await store.update_private_chat(chat.id, last_message_preview="最新的画册是否可以补货？")
    if not await store.list_feature_configs():
        await store.upsert_feature_config(
            name="涩图功能",
            description="集中管理涩图获取、审核与冷却策略。",
            options={"cooldown": "30s", "provider": "pixiv"},
        )
        await store.upsert_feature_config(
            name="自动翻译",
            description="为跨语言用户提供双语回复能力。",
            options={"defaultLocale": "zh-CN", "fallback": "en"},
        )
        await store.upsert_feature_config(
            name="活动推送",
            description="预留新品上架、直播预告等广播能力。",
            options={"schedule": "0 20 * * *"},
        )
    if not await store.list_automation_rules():
        await store.create_automation_rule(
            name="每日巡检",
            trigger="0 8 * * *",
            action="检查涩图 API 状态并推送日报",
            enabled=True,
        )
    yield

    # 应用关闭时的逻辑
    pass


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.admin_store = AdminStore()

app.include_router(admin_router.router)


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
