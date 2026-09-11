"""
telegram_bot.py - Telegram bot for Vigil AI Plus.
Runs alongside FastAPI in the same asyncio event loop.
"""
import os
import sys
import json
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logger = logging.getLogger(__name__)

CONFIG_FILE = "config.json"


# ============ Helpers ============

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def get_main_module():
    """Get the running main module so we can access BOT_PAUSED."""
    return sys.modules.get("main") or sys.modules.get("__main__")


def is_authorized(update: Update) -> bool:
    config = load_config()
    authorized = config.get("authorized_telegram_users", [])
    if not authorized:
        return False
    return update.effective_user.id in authorized


async def deny(update: Update):
    await update.message.reply_text("🚫 Unauthorized. This bot is private.")


# ============ Commands ============

async def cmd_start(update, context):
    if not is_authorized(update):
        return await deny(update)
    await update.message.reply_text(
        "🤖 *Vigil AI Plus*\n\n"
        "Commands:\n"
        "/status — Check bot status\n"
        "/pause — Pause posting\n"
        "/resume — Resume posting\n"
        "/post — Trigger test post\n"
        "/pages — List connected pages\n"
        "/queue — View scheduled posts\n"
        "/cancel `<id>` — Cancel a scheduled post",
        parse_mode="Markdown"
    )


async def cmd_status(update, context):
    if not is_authorized(update):
        return await deny(update)

    main = get_main_module()
    paused = getattr(main, "BOT_PAUSED", False)
    config = load_config()

    pages = config.get("pages", [])
    scheduled = [p for p in config.get("scheduled_affiliate_posts", []) if not p.get("posted")]

    status_emoji = "🔴 PAUSED" if paused else "🟢 RUNNING"

    text = (
        f"🤖 *Vigil AI Plus*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Status: {status_emoji}\n"
        f"Pages: {len(pages)}\n"
        f"Scheduled: {len(scheduled)} affiliate posts"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_pause(update, context):
    if not is_authorized(update):
        return await deny(update)
    main = get_main_module()
    main.BOT_PAUSED = True
    await update.message.reply_text("⏸️ Bot paused. No posts will be published until /resume.")


async def cmd_resume(update, context):
    if not is_authorized(update):
        return await deny(update)
    main = get_main_module()
    main.BOT_PAUSED = False
    await update.message.reply_text("▶️ Bot resumed. Scheduler will tick at the next minute mark.")


async def cmd_pages(update, context):
    if not is_authorized(update):
        return await deny(update)
    config = load_config()
    pages = config.get("pages", [])
    if not pages:
        return await update.message.reply_text("📭 No pages connected yet.")

    text = "📋 *Connected Pages*\n\n"
    for i, p in enumerate(pages, 1):
        name = p.get("name") or p.get("id")
        pid = p.get("id")
        interval = p.get("interval", 2)
        lang = p.get("language", "Urdu")
        text += f"{i}. *{name}*\n   ID: `{pid}`\n   Every {interval}h | {lang}\n\n"
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_queue(update, context):
    if not is_authorized(update):
        return await deny(update)
    config = load_config()
    scheduled = [p for p in config.get("scheduled_affiliate_posts", []) if not p.get("posted")]
    if not scheduled:
        return await update.message.reply_text("📭 Queue is empty.")

    text = f"📋 *Scheduled Posts* ({len(scheduled)})\n\n"
    for p in scheduled:
        name = (p.get("product_name") or "Unknown")[:50]
        time = p.get("scheduled_time", "")
        text += f"🆔 `{p.get('id')}`\n📦 {name}\n⏰ {time} UTC\n\n"
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_cancel(update, context):
    if not is_authorized(update):
        return await deny(update)
    args = context.args
    if not args:
        return await update.message.reply_text("Usage: `/cancel <post_id>`", parse_mode="Markdown")

    post_id = args[0]
    config = load_config()
    before = len(config.get("scheduled_affiliate_posts", []))
    config["scheduled_affiliate_posts"] = [
        p for p in config.get("scheduled_affiliate_posts", []) if p["id"] != post_id
    ]
    after = len(config["scheduled_affiliate_posts"])
    save_config(config)

    if before == after:
        await update.message.reply_text(f"❌ No scheduled post with ID `{post_id}`", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"✅ Cancelled scheduled post `{post_id}`", parse_mode="Markdown")


def _run_test_posts():
    """Blocking function that runs the engines for all pages."""
    try:
        from src.engines.engine_1_urdu_poetry import run_engine_1
        from src.engines.engine_2_deals import run_engine_2
        config = load_config()
        pages = config.get("pages", [])
        for idx, p in enumerate(pages):
            if idx % 2 == 0:
                run_engine_1(p)
            else:
                run_engine_2(p)
    except Exception as e:
        logger.exception(f"Test post failed: {e}")


async def cmd_post(update, context):
    if not is_authorized(update):
        return await deny(update)

    main = get_main_module()
    main.BOT_PAUSED = True  # temporarily pause to avoid scheduler collision
    await update.message.reply_text("🧪 Triggering test post... ⏳ (This runs in background)")

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_test_posts)

    main.BOT_PAUSED = False
    await update.message.reply_text("✅ Test post complete.")


# ============ Bot lifecycle ============

def build_application(token: str) -> Application:
    """Build the Telegram Application with all command handlers."""
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("pages", cmd_pages))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("post", cmd_post))
    return app