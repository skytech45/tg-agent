"""
bot/handlers.py — Telegram message handlers.

Wires together:
  - UserMemory (Redis)
  - LLM decision engine
  - Payment OCR verifier
  - Channel routing
"""

from telegram import Update, Bot
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from loguru import logger

from config import settings
from memory.redis_memory import UserMemory
from agent.llm_engine import decide_action
from payment.ocr_verifier import verify_payment_screenshot


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    memory: UserMemory,
) -> None:
    """Main handler — routes all text messages through the LLM engine."""
    user = update.effective_user
    message = update.effective_message
    if not user or not message or not message.text:
        return

    user_id = user.id
    text = message.text.strip()
    logger.info(f"[{user_id}] Message: {text[:80]}")

    # Load user context and history
    ctx = await memory.get(user_id)
    history = await memory.get_history(user_id)

    # Override role for admins
    if user_id in settings.telegram_admin_ids and ctx["role"] != "admin":
        await memory.set_role(user_id, "admin")
        ctx["role"] = "admin"

    # Store user message in history
    await memory.append_message(user_id, "user", text)

    # Ask LLM what to do
    action = await decide_action(text, ctx, history)
    await _execute_action(update, context, memory, user_id, action)


async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    memory: UserMemory,
) -> None:
    """Handle photo messages — triggers payment OCR if in payment flow."""
    user = update.effective_user
    message = update.effective_message
    if not user or not message:
        return

    user_id = user.id
    ctx = await memory.get(user_id)

    if ctx.get("flow_state") != "awaiting_payment_screenshot":
        await message.reply_text("Send /pay if you'd like to make a payment.")
        return

    await message.reply_text("🔍 Verifying your payment screenshot...")

    # Get the largest photo size
    photo = message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)
    file_url = tg_file.file_path

    result = await verify_payment_screenshot(file_url)

    if result.verified:
        await memory.set_payment_verified(user_id, True)
        await memory.set_flow_state(user_id, None)
        reply = (
            f"✅ *Payment Verified!*\n"
            f"Transaction ID: `{result.txn_id or 'N/A'}`\n"
            f"Amount: ₹{result.amount or 'N/A'}\n"
            f"Status: {result.status_text}"
        )
        await message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)

        # Log to payment channel
        if settings.telegram_payment_log_channel_id:
            log_msg = (
                f"💰 *Payment Verified*\n"
                f"User: [{user.full_name}](tg://user?id={user_id}) (`{user_id}`)\n"
                f"TXN: `{result.txn_id}`\n"
                f"Amount: ₹{result.amount}\n"
                f"Confidence: {result.confidence:.0%}"
            )
            await context.bot.send_message(
                settings.telegram_payment_log_channel_id,
                log_msg,
                parse_mode=ParseMode.MARKDOWN,
            )
    else:
        reply = f"❌ *Verification Failed*\n{result.reason}\n\nPlease try again with a clearer screenshot."
        await message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)


async def _execute_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    memory: UserMemory,
    user_id: int,
    action: dict,
) -> None:
    """Execute the action decided by the LLM engine."""
    message = update.effective_message
    bot = context.bot
    action_type = action.get("action", "reply")

    if action_type == "reply":
        text = action.get("reply_text", "...")
        await message.reply_text(text)
        await memory.append_message(user_id, "assistant", text)

    elif action_type == "request_payment":
        await memory.set_flow_state(user_id, "awaiting_payment_screenshot")
        text = (
            f"💳 *Payment Required*\n\n"
            f"Please transfer the amount to:\n`{settings.upi_id}`\n\n"
            f"Once done, send a screenshot of your payment confirmation here."
        )
        await message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    elif action_type == "route_channel":
        channel_map = {
            "client": settings.telegram_client_channel_id,
            "agent": settings.telegram_agent_channel_id,
            "payment_log": settings.telegram_payment_log_channel_id,
        }
        channel = action.get("channel", "agent")
        channel_id = channel_map.get(channel)
        if channel_id:
            user = update.effective_user
            fwd_text = (
                f"📨 *Routed from bot*\n"
                f"User: [{user.full_name}](tg://user?id={user_id}) (`{user_id}`)\n"
                f"Message: {message.text}"
            )
            await bot.send_message(channel_id, fwd_text, parse_mode=ParseMode.MARKDOWN)
            await message.reply_text("✅ Your message has been forwarded to our team.")

    elif action_type == "escalate":
        if settings.telegram_agent_channel_id:
            user = update.effective_user
            esc_text = (
                f"🚨 *Escalation Request*\n"
                f"User: [{user.full_name}](tg://user?id={user_id})\n"
                f"Message: {message.text}\n"
                f"Role: {(await memory.get(user_id)).get('role')}"
            )
            await bot.send_message(
                settings.telegram_agent_channel_id, esc_text, parse_mode=ParseMode.MARKDOWN
            )
        await message.reply_text("🔔 A human agent has been notified. We'll get back to you shortly.")

    elif action_type == "collect_info":
        question = action.get("question", action.get("reply_text", "Could you provide more details?"))
        await message.reply_text(question)

    elif action_type == "set_role":
        ctx = await memory.get(user_id)
        if ctx.get("role") == "admin":
            new_role = action.get("role", "client")
            await memory.set_role(user_id, new_role)
            await message.reply_text(f"✅ Role updated to `{new_role}`.", parse_mode=ParseMode.MARKDOWN)
        else:
            await message.reply_text("❌ You don't have permission to change roles.")

    else:
        logger.warning(f"Unknown action type: {action_type}")
        await message.reply_text(action.get("reply_text", "I'm not sure how to handle that."))
