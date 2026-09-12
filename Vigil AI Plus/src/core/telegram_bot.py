"""
telegram_bot.py - Telegram bot for Vigil AI Plus.
Runs alongside FastAPI in the same asyncio event loop.
"""
import os
import sys
import json
import uuid
import asyncio
import logging
import re
from datetime import timedelta, datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)

# Global reference to the active bot application (set at startup)
_bot_app = None

# Alert cooldowns to prevent spam (event_key → last_sent_timestamp)
_alert_cooldowns = {}
COOLDOWN_SECONDS = 300  # 5 minutes between identical alerts


async def send_alert(level: str, title: str, body: str, event_key: str = None):
    """
    Send a smart alert to the admin.
    - level: 'info' | 'warning' | 'error' | 'success'
    - title: short headline
    - body: detail text
    - event_key: deduplication key (same key won't fire twice within cooldown)
    """
    global _bot_app
    if not _bot_app:
        return

    # Cooldown check
    if event_key:
        import time as _time
        now = _time.time()
        last = _alert_cooldowns.get(event_key, 0)
        if now - last < COOLDOWN_SECONDS:
            return  # Silently skip
        _alert_cooldowns[event_key] = now

    config = load_config()
    authorized = config.get("authorized_telegram_users", [])
    if not authorized:
        return

    admin_id = authorized[0]

    emoji = {
        "info": "ℹ️",
        "warning": "⚠️",
        "error": "🚨",
        "success": "🏆",
    }.get(level, "📢")

    text = f"{emoji} *{title}*\n\n{body}"

    try:
        await _bot_app.bot.send_message(
            chat_id=admin_id,
            text=text[:4000],
            parse_mode="Markdown",
        )
        print(f"📤 Alert sent: {title}")
    except Exception as e:
        logger.warning(f"Failed to send alert: {e}")


def notify_alert_sync(level: str, title: str, body: str, event_key: str = None):
    """Sync wrapper — callable from non-async code (engines)."""
    try:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return  # No event loop, skip
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(
                send_alert(level, title, body, event_key),
                loop,
            )
        else:
            loop.run_until_complete(send_alert(level, title, body, event_key))
    except Exception as e:
        print(f"⚠️ notify_alert_sync failed: {e}")

PENDING_DIR = os.path.join("data", "pending")
os.makedirs(PENDING_DIR, exist_ok=True)


async def send_draft_notification(post_id: str, page_name: str, caption: str, image_path: str = None):
    """Send a draft to the admin for approval (called by engines)."""
    global _bot_app
    if not _bot_app:
        logger.warning("Telegram bot not ready — skipping draft notification.")
        return

    config = load_config()
    authorized = config.get("authorized_telegram_users", [])
    if not authorized:
        return

    admin_id = authorized[0]

    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{post_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{post_id}"),
        ],
        [InlineKeyboardButton("✏️ Edit Text", callback_data=f"edit_{post_id}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        f"🤖 *New Post Ready for Review*\n\n"
        f"📄 Page: *{page_name}*\n"
        f"🆔 ID: `{post_id}`\n\n"
        f"📝 Text:\n{caption[:800]}"
    )

    try:
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as img:
                await _bot_app.bot.send_photo(
                    chat_id=admin_id,
                    photo=img,
                    caption=text[:1000],
                    parse_mode="Markdown",
                    reply_markup=reply_markup,
                )
        else:
            await _bot_app.bot.send_message(
                chat_id=admin_id,
                text=text[:4000],
                parse_mode="Markdown",
                reply_markup=reply_markup,
            )
        print(f"📤 Draft {post_id} sent to Telegram for approval.")
    except Exception as e:
        logger.exception(f"Failed to send draft notification: {e}")

CONFIG_FILE = os.environ.get("CONFIG_DATA_PATH", "config.json")


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

# ============ Approval workflow ============

async def on_approve(update, context):
    """Publish an approved draft to Facebook."""
    query = update.callback_query
    await query.answer()

    if not is_authorized(update):
        return await query.edit_message_text("🚫 Unauthorized.")

    post_id = query.data.replace("approve_", "")
    config = load_config()

    draft = None
    for d in config.get("pending_approvals", []):
        if d["id"] == post_id:
            draft = d
            break

    if not draft:
        return await query.edit_message_text("❌ Draft not found (already processed?).")

    try:
        from src.core.facebook_client import post_to_facebook, post_video_to_facebook

        page = next((p for p in config.get("pages", []) if p["id"] == draft["page_id"]), None)
        if not page:
            return await query.edit_message_text("❌ Page not found.")

        image_path = draft.get("image_path")
        caption = draft.get("caption", "")
        video_url = draft.get("video_url", "")

        if video_url:
            post_id_fb = post_video_to_facebook(
                page_id=page["id"],
                access_token=page["token"],
                caption=caption,
                video_url=video_url,
            )
        else:
            post_id_fb = post_to_facebook(
                access_token=page["token"],
                page_id=page["id"],
                message=caption,
                image_path=image_path if image_path and os.path.exists(image_path) else None,
            )

        if post_id_fb:
            # Remove draft
            config["pending_approvals"] = [d for d in config["pending_approvals"] if d["id"] != post_id]
            save_config(config)

            # Cleanup image
            if image_path and os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except Exception:
                    pass

            await query.edit_message_caption(
                caption=f"✅ *Published!*\n\nPost ID: `{post_id_fb}`",
                parse_mode="Markdown",
            )
            print(f"✅ Approved & published draft {post_id} → FB ID: {post_id_fb}")
        else:
            await query.edit_message_caption(
                caption="❌ Failed to publish. Check the logs.",
            )
    except Exception as e:
        logger.exception(f"Approve failed: {e}")
        await query.edit_message_caption(caption=f"❌ Error: {e}")


async def on_reject(update, context):
    """Discard a draft."""
    query = update.callback_query
    await query.answer()

    if not is_authorized(update):
        return await query.edit_message_text("🚫 Unauthorized.")

    post_id = query.data.replace("reject_", "")
    config = load_config()

    draft = next((d for d in config.get("pending_approvals", []) if d["id"] == post_id), None)
    if not draft:
        return await query.edit_message_text("❌ Draft not found.")

    # Remove from config
    config["pending_approvals"] = [d for d in config["pending_approvals"] if d["id"] != post_id]
    save_config(config)

    # Cleanup image
    image_path = draft.get("image_path")
    if image_path and os.path.exists(image_path):
        try:
            os.remove(image_path)
        except Exception:
            pass

    await query.edit_message_caption(caption=f"🗑️ Rejected. Draft `{post_id}` discarded.")
    print(f"🗑️ Rejected draft {post_id}")


async def on_edit(update, context):
    """Ask the user to send new text for the draft."""
    query = update.callback_query
    await query.answer()

    if not is_authorized(update):
        return await query.edit_message_text("🚫 Unauthorized.")

    post_id = query.data.replace("edit_", "")
    context.user_data["editing_draft_id"] = post_id

    await query.edit_message_caption(
        caption=f"✏️ *Editing draft `{post_id}`*\n\n"
                f"Send me the new text (a single message). "
                f"It will *replace* the current caption, then I'll ask you to approve.",
        parse_mode="Markdown",
    )
    print(f"✏️ User editing draft {post_id}")


async def on_edit_text_reply(update, context):
    """Handles the new text the user sends after clicking Edit."""
    draft_id = context.user_data.get("editing_draft_id")
    if not draft_id:
        return  # Not in edit mode

    if not is_authorized(update):
        return await deny(update)

    new_text = update.message.text.strip()
    config = load_config()

    draft = next((d for d in config.get("pending_approvals", []) if d["id"] == draft_id), None)
    if not draft:
        context.user_data["editing_draft_id"] = None
        return await update.message.reply_text("❌ Draft no longer exists.")

    draft["caption"] = new_text
    save_config(config)

    context.user_data["editing_draft_id"] = None

    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{draft_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{draft_id}"),
        ],
        [InlineKeyboardButton("✏️ Edit Again", callback_data=f"edit_{draft_id}")],
    ]

    image_path = draft.get("image_path")
    try:
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as img:
                await update.message.reply_photo(
                    photo=img,
                    caption=f"🔄 *Updated draft `{draft_id}`*\n\n{new_text[:800]}",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
        else:
            await update.message.reply_text(
                f"🔄 *Updated draft `{draft_id}`*\n\n{new_text[:800]}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
    except Exception as e:
        logger.exception(f"Edit confirmation failed: {e}")
        await update.message.reply_text("✅ Text updated. Approve/reject via the original message.")


# ============ /schedule workflow ============

async def cmd_schedule(update, context):
    """Start product scheduling: /schedule watch"""
    if not is_authorized(update):
        return await deny(update)

    args = context.args
    if not args:
        return await update.message.reply_text(
            "Usage: `/schedule <search term>`\nExample: `/schedule watch`",
            parse_mode="Markdown",
        )

    search_term = " ".join(args)
    await update.message.reply_text(
        f"🔍 Searching AliExpress for: *{search_term}*...",
        parse_mode="Markdown",
    )

    try:
        from src.utils.affiliate_api import search_products

        config = load_config()
        providers = config.get("affiliate_providers", [])
        if not providers:
            return await update.message.reply_text("❌ No affiliate providers configured.")

        provider = providers[0]

        loop = asyncio.get_event_loop()
        products = await loop.run_in_executor(None, search_products, provider, search_term)

        if not products:
            return await update.message.reply_text(f"❌ No products found for '{search_term}'.")

        top5 = products[:5]

        context.user_data["schedule_products"] = top5
        context.user_data["schedule_search_term"] = search_term

        text = f"📦 Found {len(products)} products. Top 5:\n\n"
        keyboard = []
        for i, p in enumerate(top5):
            name = p.get("name", "Product")[:50]
            price = p.get("sale_price_usd", "N/A")
            text += f"*{i+1}.* {name}\n💰 ${price}\n\n"
            keyboard.append([InlineKeyboardButton(f"{i+1}. {name[:40]}", callback_data=f"pick_{i}")])

        text += "👇 Tap a product to schedule it:"
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.exception(f"Schedule search failed: {e}")
        await update.message.reply_text(f"❌ Search failed: {e}")


async def on_pick_product(update, context):
    """Handle product selection — then ask which page."""
    query = update.callback_query
    await query.answer()

    if not is_authorized(update):
        return await query.edit_message_text("🚫 Unauthorized.")

    data = query.data
    idx = int(data.split("_")[1])

    products = context.user_data.get("schedule_products", [])
    if idx >= len(products):
        return await query.edit_message_text("❌ Product no longer available. Try /schedule again.")

    selected = products[idx]
    context.user_data["schedule_selected"] = selected

    name = selected.get("name", "Product")[:60]
    price = selected.get("sale_price_usd", "N/A")

    # Load pages
    config = load_config()
    pages = config.get("pages", [])
    if not pages:
        context.user_data["awaiting_schedule_time"] = False
        return await query.edit_message_text("❌ No Facebook pages configured.")

    # Build page buttons
    keyboard = []
    for i, p in enumerate(pages):
        pname = p.get("name") or p.get("id")
        keyboard.append([InlineKeyboardButton(f"📄 {pname}", callback_data=f"page_{i}")])

    await query.edit_message_text(
        f"✅ Selected: *{name}*\n💰 ${price}\n\n"
        f"📄 Which page should I post to?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

async def on_pick_page(update, context):
    """Handle page selection — then ask for time."""
    query = update.callback_query
    await query.answer()

    if not is_authorized(update):
        return await query.edit_message_text("🚫 Unauthorized.")

    idx = int(query.data.split("_")[1])
    config = load_config()
    pages = config.get("pages", [])
    if idx >= len(pages):
        return await query.edit_message_text("❌ Page no longer available.")

    page = pages[idx]
    context.user_data["schedule_page"] = page
    selected = context.user_data.get("schedule_selected", {})
    name = selected.get("name", "Product")[:60]
    price = selected.get("sale_price_usd", "N/A")

    await query.edit_message_text(
        f"✅ Selected: *{name}*\n"
        f"💰 ${price}\n"
        f"📄 Page: *{page.get('name') or page.get('id')}*\n\n"
        f"⏰ When should I schedule it?\n"
        f"Reply with a duration, e.g.:\n"
        f"• `30m` — 30 minutes\n"
        f"• `3h` — 3 hours\n"
        f"• `1d` — 1 day",
        parse_mode="Markdown",
    )

    context.user_data["awaiting_schedule_time"] = True

async def on_time_input(update, context):
    """Handle the time reply (only fires when awaiting_schedule_time is True)."""
    if not context.user_data.get("awaiting_schedule_time"):
        return

    if not is_authorized(update):
        return await deny(update)

    text = update.message.text.strip().lower()
    match = re.match(r"^(\d+)\s*(m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)$", text)
    if not match:
        return await update.message.reply_text(
            "❌ Invalid format. Try `3h`, `30m`, or `1d`.",
            parse_mode="Markdown",
        )

    amount = int(match.group(1))
    unit = match.group(2)

    if unit.startswith("m"):
        delta = timedelta(minutes=amount)
    elif unit.startswith("h"):
        delta = timedelta(hours=amount)
    elif unit.startswith("d"):
        delta = timedelta(days=amount)
    else:
        return await update.message.reply_text("❌ Unknown unit.")

    selected = context.user_data.get("schedule_selected")
    if not selected:
        context.user_data["awaiting_schedule_time"] = False
        return await update.message.reply_text("❌ No product selected. Start with /schedule.")

    schedule_dt = datetime.now(timezone.utc) + delta
    schedule_utc_str = schedule_dt.strftime("%Y-%m-%dT%H:%M")

    config = load_config()
    if "scheduled_affiliate_posts" not in config:
        config["scheduled_affiliate_posts"] = []

    # Use the page the user selected
    page = context.user_data.get("schedule_page")
    if not page:
        context.user_data["awaiting_schedule_time"] = False
        return await update.message.reply_text("❌ No page selected. Start with /schedule.")

    new_post = {
        "id": str(uuid.uuid4())[:8],
        "page_id": page["id"],
        "provider_name": "aliexpress",
        "search_term": context.user_data.get("schedule_search_term", ""),
        "product_id": selected.get("product_id", ""),
        "product_name": selected.get("name", ""),
        "product_image": selected.get("image_url", ""),
        "product_url": selected.get("product_url", ""),
        "affiliate_link": selected.get("affiliate_link", ""),
        "sale_price_usd": selected.get("sale_price_usd", ""),
        "original_price_usd": selected.get("original_price_usd", ""),
        "currency_usd": selected.get("currency_usd", "USD"),
        "description_override": "",
        "scheduled_time": schedule_utc_str,
        "posted": False,
        "fb_post_id": None,
        "video_url": "",
        "has_video": False,
    }
    config["scheduled_affiliate_posts"].append(new_post)
    save_config(config)

    context.user_data["awaiting_schedule_time"] = False
    context.user_data["schedule_selected"] = None
    context.user_data["schedule_page"] = None

    await update.message.reply_text(
        f"✅ *Scheduled!*\n\n"
        f"🛍️ {new_post['product_name'][:60]}\n"
        f"💰 ${new_post['sale_price_usd']}\n"
        f"⏰ {schedule_utc_str} UTC\n"
        f"📄 Page: {page.get('name', page['id'])}\n"
        f"🆔 ID: `{new_post['id']}`",
        parse_mode="Markdown",
    )

async def on_text_input(update, context):
    """Unified text handler — dispatches based on current state."""
    # Priority 1: Editing a draft?
    if context.user_data.get("editing_draft_id"):
        return await on_edit_text_reply(update, context)

    # Priority 2: Awaiting schedule time?
    if context.user_data.get("awaiting_schedule_time"):
        return await on_time_input(update, context)

    # Otherwise: ignore silently (don't spam the user)
    return

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
    app.add_handler(CommandHandler("schedule", cmd_schedule))

    # Callback handlers (buttons)
    app.add_handler(CallbackQueryHandler(on_pick_product, pattern=r"^pick_"))
    app.add_handler(CallbackQueryHandler(on_pick_page, pattern=r"^page_"))
    app.add_handler(CallbackQueryHandler(on_approve, pattern=r"^approve_"))
    app.add_handler(CallbackQueryHandler(on_reject, pattern=r"^reject_"))
    app.add_handler(CallbackQueryHandler(on_edit, pattern=r"^edit_"))

    # Single unified text handler (dispatches based on state)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_input))

    global _bot_app
    _bot_app = app

    return app