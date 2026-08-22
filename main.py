import asyncio
import logging

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from telegram import Update, Bot

import bot
from bot import tg_bot

from contextlib import asynccontextmanager
from registries import engine, config_registry
from routers import (
    configs as config_routes,
    dashboard,
    groups,
    private,
    commands,
    bot_tokens,
    pixiv_tokens,
    illustrations,
)
import uvicorn

from configs import config, db_config_declare
from registries.config_registry import init_database_config
from services import pixiv, storage_service, schema_migrator
from utils.logging_config import setup_logging
from utils import frontend_launcher
from utils.admin_static import AdminStaticFiles, redirect_to_admin
from utils.api_contract import ErrorBody, ErrorResponse, error_code, error_message

setup_logging()
logger = logging.getLogger(__name__)


# TELEGRAM_TOKEN = 'AAAA'


# tg_app.add_handler(CommandHandler("start", start))


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # Tasks to run during application startup
        await engine.create_all()
        await schema_migrator.ensure_schema_migrations(engine.engine)
        await storage_service.ensure_storage_config_defaults()
        storage = await storage_service.use()
        if storage is None:
            logger.warning("No storage service set")
        else:
            await storage.get_config()
        if frontend_launcher.should_start_frontend_dev_server(
            static_build_exists=dist_dir.exists()
        ):
            await frontend_launcher.start_frontend_dev_server()
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
    finally:
        try:
            await tg_bot.shutdown()
        except Exception:
            logger.exception("Error while shutting down Telegram bot")
        try:
            await frontend_launcher.stop_frontend_dev_server()
        except Exception:
            logger.exception("Error while stopping frontend dev server")


app = FastAPI(lifespan=lifespan)


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    del request
    payload = ErrorResponse(
        error=ErrorBody(
            code=error_code(exc.status_code),
            message=error_message(exc.detail),
        )
    )
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump(exclude_none=True))


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    del request
    fields: dict[str, list[str]] = {}
    for item in exc.errors():
        location = item.get("loc") or ("request",)
        name = str(location[-1])
        fields.setdefault(name, []).append(str(item.get("msg", "参数无效")))
    payload = ErrorResponse(
        error=ErrorBody(
            code="validation_error",
            message="请求参数校验失败",
            fields=fields,
        )
    )
    return JSONResponse(status_code=422, content=payload.model_dump(exclude_none=True))

for router in (
    dashboard.router,
    groups.router,
    private.router,
    config_routes.router,
    commands.router,
    bot_tokens.router,
    pixiv_tokens.router,
    illustrations.router,
):
    app.include_router(router)

webui_dir = Path(__file__).parent / "webui"
dist_dir = webui_dir / "dist"

# 仅在生产构建产物存在时挂载 /admin；开发模式下由自动启动的 Vite dev server
# （http://localhost:5173/admin/）提供服务。
if dist_dir.exists():
    app.mount("/admin", AdminStaticFiles(directory=dist_dir, html=True), name="admin")
    app.add_api_route("/", redirect_to_admin, include_in_schema=False)
else:
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
