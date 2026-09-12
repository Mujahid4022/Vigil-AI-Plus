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

from config.config import get_api_key, get_model_name

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

def detect_language(text: str) -> str:
    """
    Fast language detector. Returns 'ur' or 'en'.
    Uses Unicode range for Urdu script + Roman Urdu keyword matching.
    """
    if not text:
        return "en"

    # 1. Check for Urdu script characters (ا ب پ ت ٹ ث ج چ ح خ د ڈ ذ ر ڑ ز ژ س ش ص ض ط ظ ع غ ف ق ک گ ل م ن و ہ ھ ی ے)
    urdu_range = re.compile(r'[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]')
    if urdu_range.search(text):
        return "ur"

    # 2. Check for Roman Urdu keywords (common verbs/words)
    roman_urdu_keywords = [
        "dikhao", "dekho", "dekha", "karo", "kro", "kar", "kya", "kya hai",
        "kaise", "kaisay", "kahan", "kab", "kyun", "kyunkay", "kyunke",
        "haan", "nahi", "nahin", "theek", "theek hai", "phir", "abhi",
        "ab", "kal", "aaj", "aur", "ke", "ka", "ki", "se", "ko",
        "mein", "main", "hum", "tum", "aap", "aapka", "mera", "meri",
        "batao", "bata", "suno", "sun", "chalo", "chal", "ruko", "ruk",
        "schedule", "post", "queue", "status",
    ]
    text_lower = text.lower()
    urdu_hits = sum(1 for kw in roman_urdu_keywords if f" {kw} " in f" {text_lower} ")

    # If 2+ Roman Urdu keywords found → treat as Urdu
    if urdu_hits >= 2:
        return "ur"

    # 3. Default to English
    return "en"

async def cmd_lang(update, context):
    """Manually set reply language: /lang ur, /lang en, /lang auto"""
    if not is_authorized(update):
        return await deny(update)

    args = context.args
    if not args:
        current = context.user_data.get("reply_language", "en")
        forced = context.user_data.get("forced_language", None)
        return await update.message.reply_text(
            f"🌐 Current reply language: *{current}*\n"
            f"Forced: *{forced or 'no (auto-detect)'}*\n\n"
            f"Usage:\n"
            f"• `/lang ur` — force Urdu replies\n"
            f"• `/lang en` — force English replies\n"
            f"• `/lang auto` — back to auto-detect",
            parse_mode="Markdown"
        )

    choice = args[0].lower().strip()

    if choice == "auto":
        context.user_data["forced_language"] = None
        return await update.message.reply_text("✅ Language set to auto-detect.")

    if choice not in ("ur", "en"):
        return await update.message.reply_text("❌ Use `/lang ur`, `/lang en`, or `/lang auto`.")

    context.user_data["forced_language"] = choice
    context.user_data["reply_language"] = choice
    await update.message.reply_text(f"✅ Language forced to `{choice}`.")

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
    lang = context.user_data.get("reply_language", "en")

    if lang.startswith("ur"):
        text = (
            f"🤖 *Vigil AI Plus*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"اسٹیٹس: {status_emoji}\n"
            f"صفحات: {len(pages)}\n"
            f"شیڈول شدہ: {len(scheduled)} پوسٹس"
        )
    else:
        text = (
            f"🤖 *Vigil AI Plus*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Status: {status_emoji}\n"
            f"Pages: {len(pages)}\n"
            f"Scheduled: {len(scheduled)} affiliate posts"
        )
    await smart_reply(update, context, text)


async def cmd_pause(update, context):
    if not is_authorized(update):
        return await deny(update)
    main = get_main_module()
    main.BOT_PAUSED = True
    lang = context.user_data.get("reply_language", "en")
    await smart_reply(
        update, context,
        _lang_text(lang,
            "⏸️ Bot paused. No posts will be published until /resume.",
            "⏸️ بوٹ روک دیا گیا۔ دوبارہ شروع کرنے تک کوئی پوسٹ نہیں ہوگی۔"
        )
    )


async def cmd_resume(update, context):
    if not is_authorized(update):
        return await deny(update)
    main = get_main_module()
    main.BOT_PAUSED = False
    lang = context.user_data.get("reply_language", "en")
    await smart_reply(
        update, context,
        _lang_text(lang,
            "▶️ Bot resumed. Scheduler will tick at the next minute mark.",
            "▶️ بوٹ دوبارہ چل پڑا۔ اگلے منٹ میں شیڈیولر کام کرے گا۔"
        )
    )


async def cmd_pages(update, context):
    if not is_authorized(update):
        return await deny(update)
    config = load_config()
    pages = config.get("pages", [])
    lang = context.user_data.get("reply_language", "en")

    if not pages:
        return await smart_reply(
            update, context,
            _lang_text(lang, "📭 No pages connected yet.", "📭 ابھی کوئی صفحہ منسلک نہیں ہے۔")
        )

    if lang.startswith("ur"):
        text = "📋 *منسلک صفحات*\n\n"
    else:
        text = "📋 *Connected Pages*\n\n"

    for i, p in enumerate(pages, 1):
        name = p.get("name") or p.get("id")
        pid = p.get("id")
        interval = p.get("interval", 2)
        plang = p.get("language", "Urdu")
        text += f"{i}. *{name}*\n   ID: `{pid}`\n   Every {interval}h | {plang}\n\n"

    await smart_reply(update, context, text)


async def cmd_queue(update, context):
    if not is_authorized(update):
        return await deny(update)
    config = load_config()
    scheduled = [p for p in config.get("scheduled_affiliate_posts", []) if not p.get("posted")]
    lang = context.user_data.get("reply_language", "en")

    if not scheduled:
        return await smart_reply(
            update, context,
            _lang_text(lang, "📭 Queue is empty.", "📭 قطار خالی ہے۔")
        )

    if lang.startswith("ur"):
        text = f"📋 *شیڈول شدہ پوسٹس* ({len(scheduled)})\n\n"
    else:
        text = f"📋 *Scheduled Posts* ({len(scheduled)})\n\n"

    for p in scheduled:
        name = (p.get("product_name") or "Unknown")[:50]
        time = p.get("scheduled_time", "")
        text += f"🆔 `{p.get('id')}`\n📦 {name}\n⏰ {time} UTC\n\n"

    await smart_reply(update, context, text)


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
    """Start product scheduling: /schedule watch (provider → product → page → time)"""
    if not is_authorized(update):
        return await deny(update)

    args = context.args
    if not args:
        return await update.message.reply_text(
            "Usage: `/schedule <search term>`\nExample: `/schedule watch`",
            parse_mode="Markdown",
        )

    search_term = " ".join(args)
    context.user_data["pending_search_term"] = search_term

    config = load_config()
    providers = config.get("affiliate_providers", [])
    if not providers:
        return await update.message.reply_text("❌ No affiliate providers configured.")

    # If only one provider, skip the picker and search directly
    if len(providers) == 1:
        await _do_schedule_search(update, context, providers[0], search_term)
        return

    # Show provider buttons
    keyboard = []
    for i, p in enumerate(providers):
        pname = p.get("nickname") or p.get("provider_type") or f"Provider {i+1}"
        keyboard.append([InlineKeyboardButton(
            f"📦 {pname}",
            callback_data=f"provider_{i}"
        )])

    await update.message.reply_text(
        f"🔍 Search term: *{search_term}*\n\n📦 Which provider should I search?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


def _get_chat_id(update_or_query):
    """Extract chat_id from Update, CallbackQuery, or Message."""
    if hasattr(update_or_query, "effective_chat") and update_or_query.effective_chat:
        return update_or_query.effective_chat.id
    if hasattr(update_or_query, "message") and update_or_query.message:
        return update_or_query.message.chat_id
    if hasattr(update_or_query, "chat_id"):
        return update_or_query.chat_id
    if hasattr(update_or_query, "id"):
        return update_or_query.id
    if hasattr(update_or_query, "chat") and update_or_query.chat:
        return update_or_query.chat.id
    return None


async def _do_schedule_search(update_or_query, context, provider, search_term):
    """Run search on given provider and send first product page."""
    chat_id = _get_chat_id(update_or_query)
    if not chat_id:
        print("⚠️ _do_schedule_search: no chat_id")
        return

    try:
        from src.utils.affiliate_api import search_products
        loop = asyncio.get_event_loop()
        products = await loop.run_in_executor(None, search_products, provider, search_term)

        if not products:
            return await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ No products found for '{search_term}'.",
            )

        context.user_data["schedule_products"] = products[:15]
        context.user_data["schedule_search_term"] = search_term
        context.user_data["schedule_page"] = 0
        context.user_data["awaiting_provider"] = provider.get("nickname") or provider.get("provider_type", "aliexpress")

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"📦 Found {len(products)} products on "
                f"*{provider.get('nickname', 'provider')}*.\n"
                f"Showing first 5 below 👇"
            ),
            parse_mode="Markdown",
        )

        await _send_product_page(update_or_query, context, page_idx=0)

    except Exception as e:
        logger.exception(f"Schedule search failed: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Search failed: {e}",
        )


async def on_pick_provider(update, context):
    """Handle provider selection — run search and show products."""
    query = update.callback_query
    await query.answer()

    if not is_authorized(update):
        return

    idx = int(query.data.split("_")[1])
    config = load_config()
    providers = config.get("affiliate_providers", [])
    if idx >= len(providers):
        return await query.edit_message_text("❌ Provider not found.")

    provider = providers[idx]
    search_term = context.user_data.get("pending_search_term", "")
    if not search_term:
        return await query.edit_message_text("❌ No search term. Start with /schedule.")

    await query.edit_message_text(
        f"🔍 Searching *{provider.get('nickname', 'provider')}* for: *{search_term}*...",
        parse_mode="Markdown",
    )

    await _do_schedule_search(update, context, provider, search_term)


async def _send_product_page(update_or_query, context, page_idx: int):
    """Send 5 products with images + a Next button if more available."""
    products = context.user_data.get("schedule_products", [])
    if not products:
        return

    start = page_idx * 5
    end = start + 5
    page_products = products[start:end]

    # ---- Determine chat_id (works for Update, Chat, Message, CallbackQuery) ----
    chat_id = None
    if hasattr(update_or_query, "effective_chat") and update_or_query.effective_chat:
        chat_id = update_or_query.effective_chat.id
    elif hasattr(update_or_query, "message") and update_or_query.message:
        chat_id = update_or_query.message.chat_id
    elif hasattr(update_or_query, "chat_id"):
        chat_id = update_or_query.chat_id
    elif hasattr(update_or_query, "id"):
        chat_id = update_or_query.id
    elif hasattr(update_or_query, "chat") and update_or_query.chat:
        chat_id = update_or_query.chat.id

    if not chat_id:
        print("⚠️ _send_product_page: could not determine chat_id")
        return

    for i, p in enumerate(page_products):
        global_idx = start + i
        name = (p.get("name") or "Product")[:120]
        price = p.get("sale_price_usd", "N/A")
        image_url = p.get("image_url", "")
        caption = f"*{global_idx + 1}.* {name}\n💰 ${price}"

        keyboard = [[
            InlineKeyboardButton(
                f"✅ Select #{global_idx + 1}",
                callback_data=f"pick_{global_idx}"
            )
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            if image_url:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=image_url,
                    caption=caption,
                    parse_mode="Markdown",
                    reply_markup=reply_markup,
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    parse_mode="Markdown",
                    reply_markup=reply_markup,
                )
        except Exception as img_err:
            print(f"⚠️ Photo failed for product {global_idx}: {img_err}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=caption,
                parse_mode="Markdown",
                reply_markup=reply_markup,
            )

    # ---- Send nav buttons if there are more ----
    has_more = end < len(products)
    if has_more:
        next_page_idx = page_idx + 1
        nav_keyboard = [[
            InlineKeyboardButton(
                "⬅️ Previous 5" if page_idx > 0 else "❌ Cancel",
                callback_data=f"spage_{page_idx - 1}" if page_idx > 0 else "spage_cancel"
            ),
            InlineKeyboardButton(
                "Next 5 ➡️",
                callback_data=f"spage_{next_page_idx}"
            ),
        ]]
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📄 Showing {start + 1}–{end} of {len(products)}",
            reply_markup=InlineKeyboardMarkup(nav_keyboard),
        )
    else:
        if page_idx > 0:
            nav_keyboard = [[
                InlineKeyboardButton(
                    "⬅️ Previous 5",
                    callback_data=f"spage_{page_idx - 1}"
                )
            ]]
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"📄 Showing {start + 1}–{len(products)} of {len(products)} (end)",
                reply_markup=InlineKeyboardMarkup(nav_keyboard),
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"📄 Showing {start + 1}–{len(products)} of {len(products)} (end)"
            )


async def on_schedule_page(update, context):
    """Handle pagination buttons (Next 5 / Previous 5 / Cancel)."""
    query = update.callback_query
    await query.answer()

    if not is_authorized(update):
        return

    data = query.data

    if data == "spage_cancel":
        context.user_data["schedule_products"] = None
        await query.edit_message_text("❌ Browse cancelled. Use /schedule to start again.")
        return

    try:
        page_idx = int(data.replace("spage_", ""))
    except ValueError:
        return

    if page_idx < 0:
        return

    await query.edit_message_text(f"📄 Loading page {page_idx + 1}...")

    await _send_product_page(update, context, page_idx=page_idx)
    context.user_data["schedule_page"] = page_idx


async def on_pick_product(update, context):
    """Handle product selection — send a page picker tied to this product."""
    query = update.callback_query
    await query.answer()

    if not is_authorized(update):
        return

    idx = int(query.data.split("_")[1])
    products = context.user_data.get("schedule_products", [])
    if idx >= len(products):
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ Product no longer available. Try /schedule again.",
        )
        return

    selected = products[idx]
    name = selected.get("name", "Product")[:60]
    price = selected.get("sale_price_usd", "N/A")

    config = load_config()
    pages = config.get("pages", [])
    if not pages:
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ No Facebook pages configured.",
        )
        return

    # Encode BOTH page index AND product index in callback data
    keyboard = []
    for i, p in enumerate(pages):
        pname = p.get("name") or p.get("id")
        keyboard.append([InlineKeyboardButton(
            f"📄 {pname}",
            callback_data=f"page_{i}_{idx}"   # <-- includes product idx
        )])

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=(
            f"✅ Selected: *{name}*\n"
            f"💰 ${price}\n\n"
            f"📄 Which page should I post to?"
        ),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

async def on_pick_page(update, context):
    """Handle page selection — ask for time for THIS specific product."""
    query = update.callback_query
    await query.answer()

    if not is_authorized(update):
        return

    parts = query.data.split("_")   # ["page", page_idx, prod_idx]
    if len(parts) != 3:
        return
    page_idx = int(parts[1])
    prod_idx = int(parts[2])

    config = load_config()
    pages = config.get("pages", [])
    products = context.user_data.get("schedule_products", [])

    if page_idx >= len(pages) or prod_idx >= len(products):
        return await query.edit_message_text("❌ Selection expired. Start with /schedule.")

    page = pages[page_idx]
    selected = products[prod_idx]

    # Store the awaiting state — this is the CURRENT flow
    context.user_data["awaiting_product"] = selected
    context.user_data["awaiting_page"] = page
    context.user_data["awaiting_schedule_time"] = True

    await query.edit_message_text(
        f"✅ Selected: *{selected.get('name', '')[:60]}*\n"
        f"💰 ${selected.get('sale_price_usd', 'N/A')}\n"
        f"📄 Page: *{page.get('name') or page.get('id')}*\n\n"
        f"⏰ When should I schedule it?\n"
        f"Reply with a duration, e.g. `30m`, `3h`, `1d`",
        parse_mode="Markdown",
    )

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

    selected = context.user_data.get("awaiting_product")
    if not selected:
        context.user_data["awaiting_schedule_time"] = False
        return await update.message.reply_text("❌ No product selected. Start with /schedule.")

    schedule_dt = datetime.now(timezone.utc) + delta
    schedule_utc_str = schedule_dt.strftime("%Y-%m-%dT%H:%M")

    config = load_config()
    if "scheduled_affiliate_posts" not in config:
        config["scheduled_affiliate_posts"] = []

    # Use the page the user selected
    page = context.user_data.get("awaiting_page")
    if not page:
        context.user_data["awaiting_schedule_time"] = False
        return await update.message.reply_text("❌ No page selected. Start with /schedule.")

    new_post = {
        "id": str(uuid.uuid4())[:8],
        "page_id": page["id"],
        "provider_name": context.user_data.get("awaiting_provider", "aliexpress"),
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
    context.user_data["awaiting_product"] = None
    context.user_data["awaiting_page"] = None
    context.user_data["awaiting_provider"] = None
    context.user_data["pending_search_term"] = None

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
    """Unified text handler — detects language, then dispatches based on state."""
    # Text input → don't send voice reply (voice flag off)
    context.user_data["last_input_was_voice"] = False

    # Detect language of this message and store for reply
    try:
        detected = detect_language(update.message.text or "")
        context.user_data["reply_language"] = detected
        print(f"🌐 Text language detected: {detected}")
    except Exception as e:
        print(f"⚠️ Language detect failed: {e}")

    # Priority 1: Editing a draft?
    if context.user_data.get("editing_draft_id"):
        return await on_edit_text_reply(update, context)

    # Priority 2: Awaiting schedule time?
    if context.user_data.get("awaiting_schedule_time"):
        return await on_time_input(update, context)

    # Otherwise: ignore silently
    return

# ============ Voice command support ============

def _lang_text(lang: str, en_text: str, ur_text: str) -> str:
    """Return text in the correct language based on detected input language."""
    if lang and lang.startswith("ur"):
        return ur_text
    return en_text


async def on_voice_message(update, context):
    """Handle voice notes — transcribe + parse + execute + reply with voice + text."""
    if not is_authorized(update):
        return await deny(update)

    voice = update.message.voice
    if not voice:
        return

    # Download voice file
    try:
        file = await context.bot.get_file(voice.file_id)
        import tempfile
        tmp_path = os.path.join(tempfile.gettempdir(), f"voice_{voice.file_unique_id}.ogg")
        await file.download_to_drive(tmp_path)
    except Exception as e:
        return await update.message.reply_text(f"❌ Could not download voice: {e}")

    # Acknowledge (voice + text)
    context.user_data["last_input_was_voice"] = True
    await update.message.reply_text("🎤 Transcribing...")

    # Transcribe
    from src.utils.voice_processor import transcribe_voice
    config = load_config()
    stt_provider = config.get("stt_provider", "groq")

    result = await transcribe_voice(tmp_path, provider_name=stt_provider, language=None)

    # Cleanup
    try:
        os.remove(tmp_path)
    except Exception:
        pass

    if not result or not result.get("text"):
        context.user_data["reply_language"] = "en"
        return await smart_reply(
            update, context,
            "❌ Could not understand the voice note. Please try again.\n"
            "❌ آواز سمجھ نہیں آئی۔ دوبارہ کوشش کریں۔",
        )

    text = result["text"]
    whisper_lang = result["language"]   # Groq's guess (may be wrong)

    # Parse intent — LLM will also tell us the real language
    intent = await _parse_voice_intent(text, whisper_lang)

    # Prefer the LLM's language detection over Groq's
    llm_lang = intent.get("language") if intent else None
    lang = llm_lang or whisper_lang or "en"

    print(f"🌐 Language: whisper={whisper_lang}, llm={llm_lang}, using={lang}")
    context.user_data["reply_language"] = lang

    if not intent or intent.get("intent") == "unknown":
        return await smart_reply(
            update, context,
            _lang_text(lang,
                f"🎤 Heard: _{text}_\n\n❌ No matching command.",
                f"🎤 سنا: _{text}_\n\n❌ کوئی کمانڈ نہیں ملی۔"
            )
        )

    # Route intent — but use a special flag so cmd_* helpers know to reply via voice
    await _execute_voice_intent(intent, update, context, text, lang)


async def _parse_voice_intent(text, lang):
    """Use LLM to extract intent + parameters + correct language."""
    prompt = f"""You are a command parser for a Facebook automation bot.

User said (may contain transcription errors): "{text}"

Available intents:
- schedule_product (needs: search_term) — user wants to schedule a product to post
- queue_status — user wants to see scheduled posts
- pause_bot — pause all posting
- resume_bot — resume posting
- bot_status — check bot status
- list_pages — list connected Facebook pages
- post_now — trigger immediate test post
- cancel_post (needs: post_id) — cancel a scheduled post

Respond ONLY with valid JSON, no extra text.
Also detect the language of the user's speech:
- If the text is in Urdu script (اردو) → language = "ur"
- If the text is Roman Urdu (Urdu words in English letters, e.g. "status dikhao", "queue dekho", "pause karo", "teen ghante") → language = "ur"
- If the text is pure English → language = "en"

Examples:
{{"intent": "bot_status", "language": "ur"}}
{{"intent": "pause_bot", "language": "en"}}
{{"intent": "schedule_product", "search_term": "watch", "language": "ur"}}
{{"intent": "unknown", "language": "en"}}"""

    # Use Groq
    try:
        api_key = get_api_key("groq")
        if not api_key:
            return None
        from groq import Groq
        client = Groq(api_key=api_key)
        model = get_model_name("groq") or "openai/gpt-oss-120b"
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        import json as _json
        return _json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"⚠️ Intent parse failed: {e}")
        return None


async def _execute_voice_intent(intent, update, context, raw_text, lang):
    """Route parsed intent to existing command handlers (they'll send text+voice)."""
    intent_type = intent.get("intent", "unknown")

    # The command handlers below were written for TEXT input.
    # We bypass their direct reply_text by wrapping them.
    # Since they call update.message.reply_text directly, we temporarily
    # patch it to also fire TTS.

    # Simplest approach: let them run, then send a follow-up voice.
    # We do a two-pass: run the handler, then send voice of the SAME text.

    if intent_type == "schedule_product":
        search_term = (intent.get("search_term") or "").strip()
        if not search_term:
            return await smart_reply(
                update, context,
                _lang_text(lang, "❌ No product name detected.", "❌ پروڈکٹ کا نام نہیں ملا۔")
            )
        context.args = search_term.split()
        return await cmd_schedule(update, context)

    if intent_type == "queue_status":
        return await cmd_queue(update, context)

    if intent_type == "pause_bot":
        return await cmd_pause(update, context)

    if intent_type == "resume_bot":
        return await cmd_resume(update, context)

    if intent_type == "bot_status":
        return await cmd_status(update, context)

    if intent_type == "list_pages":
        return await cmd_pages(update, context)

    if intent_type == "post_now":
        return await cmd_post(update, context)

    if intent_type == "cancel_post":
        post_id = (intent.get("post_id") or "").strip()
        if post_id:
            context.args = [post_id]
            return await cmd_cancel(update, context)
        return await smart_reply(update, context, "❌ No post ID detected.")

    return await smart_reply(
        update, context,
        _lang_text(lang,
            f"🎤 Heard: _{raw_text}_\n\n❌ Unknown command.",
            f"🎤 سنا: _{raw_text}_\n\n❌ نامعلوم کمانڈ۔"
        )
    )
# ============ Voice reply helpers ============

async def smart_reply(update, context, text: str, force_voice: bool = None):
    """
    Send a reply. If last input was voice, also send TTS voice note.
    Language is taken from context.user_data['reply_language'].
    """
    lang = context.user_data.get("reply_language", "en")
    last_was_voice = context.user_data.get("last_input_was_voice", False)

    should_send_voice = last_was_voice if force_voice is None else force_voice

    # Always send text
    try:
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(text)  # fallback if markdown breaks

    # Optionally send voice
    if should_send_voice:
        try:
            from src.utils.tts_processor import synthesize_speech
            config = load_config()
            tts_provider = config.get("tts_provider", "gtts")

            audio_path = synthesize_speech(text, language=lang, provider_name=tts_provider)

            if audio_path and os.path.exists(audio_path):
                with open(audio_path, "rb") as audio:
                    await update.message.reply_voice(voice=audio)
                # Cleanup
                try:
                    os.remove(audio_path)
                except Exception:
                    pass
            else:
                print("⚠️ TTS returned no audio file")
        except Exception as e:
            print(f"⚠️ Voice reply failed: {e}")

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
    app.add_handler(CommandHandler("lang", cmd_lang))

    # Callback handlers (buttons)
    app.add_handler(CallbackQueryHandler(on_pick_provider, pattern=r"^provider_"))
    app.add_handler(CallbackQueryHandler(on_pick_product, pattern=r"^pick_"))
    app.add_handler(CallbackQueryHandler(on_schedule_page, pattern=r"^spage_"))
    app.add_handler(CallbackQueryHandler(on_pick_page, pattern=r"^page_"))
    app.add_handler(CallbackQueryHandler(on_approve, pattern=r"^approve_"))
    app.add_handler(CallbackQueryHandler(on_reject, pattern=r"^reject_"))
    app.add_handler(CallbackQueryHandler(on_edit, pattern=r"^edit_"))

    # Single unified text handler (dispatches based on state)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_input))
    # Voice message handler
    app.add_handler(MessageHandler(filters.VOICE, on_voice_message))
    global _bot_app
    _bot_app = app

    return app