"""
main.py — FastAPI + python-telegram-bot webhook server.

Run:
    uvicorn main:app --host 0.0.0.0 --port 8000

Set webhook:
    https://api.telegram.org/bot<TOKEN>/setWebhook?url=<WEBHOOK_URL>/webhook
"""

from contextlib import asynccontextmanager
import json

from fastapi import FastAPI, Request, Response
from loguru import logger
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from config import settings
from memory.redis_memory import UserMemory, get_redis
from bot.handlers import handle_message, handle_photo


# ── Global state ──
_app_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("Starting tg-agent...")

    redis = await get_redis()
    memory = UserMemory(redis)
    _app_state["memory"] = memory

    tg_app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    # Register command handlers
    async def start(update, context):
        await update.message.reply_text(
            "👋 Hello! I'm your AI agent.\n\n"
            "Type anything to get started, or use /help for available commands."
        )

    async def help_cmd(update, context):
        await update.message.reply_text(
            "📋 *Available Commands*\n\n"
            "/start — Welcome message\n"
            "/pay  — Make a payment\n"
            "/status — Check your account status\n"
            "/help — Show this message",
            parse_mode="Markdown"
        )

    async def pay_cmd(update, context):
        await memory.set_flow_state(update.effective_user.id, "awaiting_payment_screenshot")
        await update.message.reply_text(
            f"💳 Please send your UPI payment to:\n`{settings.upi_id}`\n\n"
            "After paying, send a screenshot here for verification.",
            parse_mode="Markdown"
        )

    async def status_cmd(update, context):
        ctx = await memory.get(update.effective_user.id)
        await update.message.reply_text(
            f"👤 *Your Status*\n"
            f"Role: `{ctx.get('role', 'client')}`\n"
            f"Payment Verified: {'✅' if ctx.get('payment_verified') else '❌'}\n"
            f"Member Since: {ctx.get('joined_at', 'N/A')[:10]}",
            parse_mode="Markdown"
        )

    async def text_handler(update, context):
        await handle_message(update, context, memory)

    async def photo_handler(update, context):
        await handle_photo(update, context, memory)

    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(CommandHandler("help", help_cmd))
    tg_app.add_handler(CommandHandler("pay", pay_cmd))
    tg_app.add_handler(CommandHandler("status", status_cmd))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    tg_app.add_handler(MessageHandler(filters.PHOTO, photo_handler))

    await tg_app.initialize()
    _app_state["tg_app"] = tg_app

    logger.success("tg-agent ready ✅")
    yield

    await tg_app.shutdown()
    await redis.aclose()
    logger.info("tg-agent shut down.")


app = FastAPI(title="tg-agent", lifespan=lifespan)


@app.post("/webhook")
async def webhook(request: Request):
    """Receive Telegram updates via webhook."""
    tg_app = _app_state.get("tg_app")
    if not tg_app:
        return Response(status_code=503)

    data = await request.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return Response(status_code=200)


@app.get("/health")
async def health():
    return {"status": "ok", "bot": settings.telegram_bot_token[:10] + "..."}
