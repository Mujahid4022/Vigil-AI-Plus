"""
Vigil AI Plus - FastAPI version
Migrated from Flask run.py
"""
import os
import json
import time
import threading
import requests
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from config.config import get_api_key, get_model_name
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi.staticfiles import StaticFiles
from typing import Optional
import secrets
import uuid
import pytz
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Depends, HTTPException, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response

# --- Configuration ---
CONFIG_FILE = "config.json"

DRIVER_FILE = "src/utils/provider_drivers.json"


def load_drivers():
    """Load the provider driver templates from JSON file."""
    if os.path.exists(DRIVER_FILE):
        with open(DRIVER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    default_config = {
        "api_keys": {},
        "pages": [],
        "daily_requests": {},
        "daily_imagen_requests": {},
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(default_config, f, indent=4)
    return default_config

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

def get_facebook_page_name(page_id, access_token):
    """Fetches the actual Facebook Page name using the Graph API."""
    try:
        url = f"https://graph.facebook.com/v26.0/{page_id}?fields=name&access_token={access_token}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json().get('name', '')
        return None
    except:
        return None

def fetch_video_from_product_page(product_url):
    """Simple requests-based video detection – works only if video URL is in static HTML."""
    try:
        import re
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(product_url, headers=headers, timeout=10)
        html = resp.text

        # Try to find videoUrl in the page's JSON
        match = re.search(r'"videoUrl"\s*:\s*"([^"]+)"', html)
        if match:
            url = match.group(1)
            if url.startswith('http'):
                return url

        # Look for .mp4 links directly
        match = re.search(r'https?://[^"\' ]+\.mp4[^"\' ]*', html)
        if match:
            return match.group(0)

        return None
    except Exception:
        return None


def update_env_token(page_id, new_token):
    """Updates the .env file with a dynamic key based on page_id."""
    env_file = ".env"
    if not os.path.exists(env_file):
        return

    with open(env_file, "r") as f:
        lines = f.readlines()

    env_key = f"FB_ACCESS_TOKEN_{page_id}"
    updated = False

    with open(env_file, "w") as f:
        for line in lines:
            if line.startswith(f"{env_key}="):
                f.write(f"{env_key}={new_token}\n")
                updated = True
            else:
                f.write(line)
        if not updated:
            f.write(f"{env_key}={new_token}\n")

    print(f"✅ .env file synced: {env_key} updated.")



# ========== GLOBAL BOT STATE ==========
BOT_PAUSED = False
scheduler = BackgroundScheduler(timezone="UTC")


def scheduled_tick():
    if BOT_PAUSED:
        print("⏸️ Bot is paused. Skipping tick.")
        return

    # ---- 1. PROCESS AFFILIATE POSTS FIRST (fast, time-sensitive) ----
    try:
        process_affiliate_posts()
    except Exception as e:
        print(f"❌ Affiliate processing error: {e}")

    try:
        from src.engines.engine_1_urdu_poetry import run_engine_1
        from src.engines.engine_2_deals import run_engine_2
    except Exception as e:
        print(f"⚠️ Could not import engines: {e}")
        return

    config = load_config()
    now = time.time()
    pages = config.get("pages", [])

    for idx, p in enumerate(pages):
        # ---- Posting Logic (interval-based) ----
        if (now - p.get("last_posted", 0)) > (p.get("interval", 2) * 3600):
            print(f"⏰ Posting for {p['id']} (Index: {idx})")
            try:
                if idx % 2 == 0:
                    print("🔄 Using Engine 1")
                    run_engine_1(p)
                else:
                    print("🔄 Using Engine 2")
                    run_engine_2(p)
                p["last_posted"] = now
                save_config(config)
            except Exception as e:
                print(f"❌ Engine error for page {p['id']}: {e}")

def run_engagement_all_pages():
    """Run engagement for all pages once every 24h (separate from main tick)."""
    try:
        from src.engines.engine_engagement import run_engagement
    except Exception as e:
        print(f"⚠️ Could not import engagement: {e}")
        return

    config = load_config()
    now = time.time()

    for p in config.get("pages", []):
        try:
            print(f"🤝 Running engagement for {p['id']}")
            run_engagement(p)
            p["last_engagement"] = now
            save_config(config)
        except Exception as e:
            print(f"❌ Engagement error for page {p['id']}: {e}")

def process_affiliate_posts():
    """Check and publish due affiliate posts."""
    from datetime import datetime as dt

    config = load_config()
    scheduled_posts = config.get("scheduled_affiliate_posts", [])
    if not scheduled_posts:
        return

    now = time.time()
    for post in list(scheduled_posts):
        if post.get("posted"):
            continue
        try:
            post_time = dt.strptime(post["scheduled_time"], "%Y-%m-%dT%H:%M")
            if now >= post_time.timestamp():
                print(f"⏰ Affiliate post due for: {post.get('search_term', 'No term')}")
                page = next((p for p in config.get("pages", []) if p["id"] == post["page_id"]), None)
                if not page:
                    print(f"❌ Page {post['page_id']} not found. Removing from queue.")
                    config["scheduled_affiliate_posts"] = [
                        p for p in config["scheduled_affiliate_posts"] if p["id"] != post["id"]
                    ]
                    save_config(config)
                    continue

                post_id = post_affiliate_product(post, page)
                if post_id:
                    config["scheduled_affiliate_posts"] = [
                        p for p in config["scheduled_affiliate_posts"] if p["id"] != post["id"]
                    ]
                    save_config(config)
                    print(f"✅ Affiliate post published! ID: {post_id} (Removed from queue)")
                else:
                    print(f"❌ Failed to post affiliate product. Will retry next tick.")
        except Exception as e:
            print(f"⚠️ Error processing scheduled post {post.get('id', 'unknown')}: {e}")
            import traceback
            traceback.print_exc()


def post_affiliate_product(scheduled_post, page):
    """Generate post text with AI and publish to Facebook."""
    from src.utils.affiliate_api import search_products
    from src.core.facebook_client import (
        post_to_facebook,
        post_video_to_facebook,
        get_post_insights,
    )
    from src.engines.engine_1_urdu_poetry import log_performance

    config = load_config()

    # Find provider
    provider = None
    for p in config.get("affiliate_providers", []):
        if p["nickname"] == scheduled_post["provider_name"]:
            provider = p
            break

    if not provider:
        print(f"❌ Provider '{scheduled_post['provider_name']}' not found.")
        return None

    # Fetch products
    products = search_products(provider, scheduled_post["search_term"])
    if not products:
        print(f"❌ No products found for '{scheduled_post['search_term']}'.")
        return None

    # Find the specific product by ID
    stored_product_id = scheduled_post.get("product_id")
    product = None
    if stored_product_id:
        product = next(
            (p for p in products if str(p.get("product_id", "")) == str(stored_product_id)),
            None,
        )
    if not product:
        print(f"⚠️ Product with ID {stored_product_id} not found. Using first product.")
        product = products[0]

    affiliate_link = product.get("affiliate_link") or product.get("product_url", "")

    # Prices
    sale_usd = product.get("sale_price_usd", "N/A")
    original_usd = product.get("original_price_usd", "N/A")
    currency_usd = product.get("currency_usd", "USD")

    if sale_usd != "N/A" and original_usd != "N/A":
        try:
            sale = float(sale_usd)
            original = float(original_usd)
            if original > 0:
                discount = int(((original - sale) / original) * 100)
                price_display = f"💰 DEAL: {discount}% OFF!\n🪙 Now only ${sale:.2f} — was ${original:.2f}"
            else:
                price_display = f"🪙 Now only ${sale:.2f}"
        except Exception:
            price_display = f"🪙 Now only ${sale_usd}"
    else:
        price_display = f"🪙 Now only ${sale_usd}"

    print(f"💰 Price (USD): {price_display}")

    # Build AI prompt
    product_name = product.get("name", "Product")
    product_description = product.get("description", "")

    prompt = f"""
You are a social media copywriter for a Facebook page.

Page Brief: {page.get('brief', '')}

Product Details:
- Name: {product_name}
- Description: {product_description}
- Price: {price_display}
- Affiliate Link: {affiliate_link}

Write a short, engaging Facebook post that promotes this product. Use emojis. Keep it under 200 words.
The post should have:
- A catchy headline
- The price section (already provided)
- Bullet points highlighting key features
- A call to action
- End with the affiliate link on a new line.
- Do not include any extra text beyond the post.
"""

    # Generate with AI
    formatted_post = None
    priority_list = page.get("provider_priority", "gemini").split(",")
    priority_list = [p.strip() for p in priority_list if p.strip()]

    for provider_name in priority_list:
        api_key = get_api_key(provider_name)
        if not api_key:
            continue
        try:
            if provider_name == "groq":
                from groq import Groq
                model = get_model_name("groq") or "openai/gpt-oss-120b"
                client = Groq(api_key=api_key)
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                )
                formatted_post = response.choices[0].message.content
                break
            else:
                from google import genai
                model = get_model_name(provider_name) or "models/gemini-3.5-flash"
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(model=model, contents=prompt)
                formatted_post = response.text.strip()
                break
        except Exception as e:
            print(f"⚠️ AI provider {provider_name} failed: {e}")
            continue

    if not formatted_post:
        formatted_post = f"""🔥 NEW DEAL ALERT! 🇵🇰

🛍️ {product.get('name', 'Product')}
{price_display}

🔗 Grab it now: {affiliate_link}

#DealAlert #Pakistan #Shopping"""

    # Post to Facebook
    video_url = scheduled_post.get("video_url") or product.get("video_url")
    image_url = scheduled_post.get("product_image") or product.get("image_url")

    print(f"🔍 DEBUG: video_url = {video_url}")
    print(f"🔍 DEBUG: image_url = {image_url}")

    if video_url:
        print(f"🎬 Posting video: {video_url[:100]}...")
        post_id = post_video_to_facebook(
            page_id=page["id"],
            access_token=page["token"],
            caption=formatted_post,
            video_url=video_url,
        )
    elif image_url:
        print(f"📸 Posting image: {image_url[:100]}...")
        post_id = post_to_facebook(
            access_token=page["token"],
            page_id=page["id"],
            message=formatted_post,
            image_url=image_url,
        )
    else:
        post_id = post_to_facebook(
            access_token=page["token"],
            page_id=page["id"],
            message=formatted_post,
            image_url=None,
        )

    if post_id:
        insights = get_post_insights(post_id, page["token"])
        log_performance(post_id, insights, page["id"])
        print(f"📊 Analytics logged for post: {post_id}")
    else:
        print("❌ No post ID returned.")

    return post_id


# --- Lifespan (startup / shutdown) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start scheduler + Telegram bot on boot; stop both on shutdown."""
    print("🚀 Starting Vigil AI Plus (FastAPI)...")

    # ---- APScheduler ----
    scheduler.add_job(
        scheduled_tick,
        "interval",
        seconds=60,
        id="vigil_tick",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        run_engagement_all_pages,
        "interval",
        hours=24,
        id="engagement_job",
        replace_existing=True,
    )

    scheduler.start()
    print("✅ APScheduler started (every 60s).")

    # ---- Telegram Bot ----
    tg_app = None
    config = load_config()
    token = config.get("telegram_bot_token", "").strip()

    if token and "PASTE" not in token and "YOUR" not in token:
        try:
            from src.core.telegram_bot import build_application
            tg_app = build_application(token)
            await tg_app.initialize()
            await tg_app.start()
            await tg_app.updater.start_polling()
            print("✅ Telegram bot started.")
        except Exception as e:
            print(f"⚠️ Telegram bot failed to start: {e}")
            tg_app = None
    else:
        print("ℹ️ Telegram token not set. Skipping bot.")

    yield

    # ---- Shutdown ----
    if tg_app:
        try:
            await tg_app.updater.stop()
            await tg_app.stop()
            await tg_app.shutdown()
            print("🛑 Telegram bot stopped.")
        except Exception:
            pass

    scheduler.shutdown()
    print("🛑 APScheduler stopped.")


# --- FastAPI App ---
app = FastAPI(
    title="Vigil AI Plus API",
    description="FastAPI backend for Vigil AI Plus - social media automation",
    version="1.0.0",
    lifespan=lifespan,
)

# --- Templates ---
templates = Jinja2Templates(directory="templates")

# --- Authentication ---
USERNAME = "admin"
PASSWORD = "vigilai4042"

security = HTTPBasic()

def verify_auth(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, USERNAME)
    correct_password = secrets.compare_digest(credentials.password, PASSWORD)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# =========================================================
# ROUTES
# =========================================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, user: str = Depends(verify_auth)):
    """Main dashboard."""
    config = load_config()
    twitter_creds = config.get("twitter_credentials", {})
    twitter_configured = bool(
        twitter_creds.get("consumer_key") and
        twitter_creds.get("consumer_secret") and
        twitter_creds.get("access_token") and
        twitter_creds.get("access_token_secret")
    )
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "api_keys": config.get("api_keys", {}),
            "pages": config.get("pages", []),
            "agnes_api_key": config.get("agnes_api", {}).get("key", ""),
            "bot_paused": BOT_PAUSED,
            "twitter_configured": twitter_configured,
            "twitter": twitter_creds,
            "telegram_token": config.get("telegram_bot_token", ""),
            "authorized_users": ",".join([str(uid) for uid in config.get("authorized_telegram_users", [])]),
            "lead_webhook": config.get("lead_webhook_url", ""),
            "pinterest": config.get("pinterest_credentials", {}),
            "message": "Vigil AI Plus is running on FastAPI 🚀"
        }
    )


@app.post("/add_api_key")
async def add_api_key(
    ai_provider: str = Form(...),
    api_key: str = Form(...),
    model_name: str = Form(""),
    user: str = Depends(verify_auth),
):
    """Save an AI provider API key."""
    config = load_config()
    if "api_keys" not in config:
        config["api_keys"] = {}
    config["api_keys"][ai_provider] = {
        "key": api_key.strip(),
        "model": model_name.strip()
    }
    save_config(config)
    print(f"✅ Saved API key for {ai_provider}")
    return RedirectResponse(url="/", status_code=303)


@app.post("/delete_api_key/{provider}")
async def delete_api_key(provider: str, user: str = Depends(verify_auth)):
    """Delete an AI provider API key."""
    config = load_config()
    if provider in config.get("api_keys", {}):
        del config["api_keys"][provider]
        save_config(config)
        print(f"🗑️ Deleted API key for {provider}")
    return RedirectResponse(url="/", status_code=303)


@app.post("/add_agnes_key")
async def add_agnes_key(
    agnes_api_key: str = Form(""),
    user: str = Depends(verify_auth),
):
    """Save the Agnes AI image generation key."""
    config = load_config()
    if "agnes_api" not in config:
        config["agnes_api"] = {}
    config["agnes_api"]["key"] = agnes_api_key.strip()
    save_config(config)
    print(f"✅ Agnes AI key saved.")
    return RedirectResponse(url="/", status_code=303)


@app.post("/add_page")
async def add_page(
    page_id: str = Form(...),
    page_name: str = Form(""),
    page_token: str = Form(...),
    ai_provider: str = Form("gemini"),
    post_language: str = Form("Urdu"),
    brief: str = Form(""),
    provider_priority: str = Form("gemini"),
    posts_per_run: int = Form(2),
    post_interval: int = Form(30),
    instagram_id: str = Form(""),
    twitter_enabled: str = Form(None),
    lead_webhook: str = Form(""),
    interval_hours: int = Form(2),
    user: str = Depends(verify_auth),
):
    """Add a new Facebook Page."""
    config = load_config()
    # Check for duplicates
    if not any(p["id"] == page_id for p in config["pages"]):
        config["pages"].append({
            "id": page_id,
            "name": page_name,
            "token": page_token,
            "ai_provider": ai_provider,
            "language": post_language,
            "brief": brief,
            "urls": [],
            "interval": interval_hours,
            "last_posted": 0,
            "provider_priority": provider_priority,
            "posts_per_run": posts_per_run,
            "post_interval": post_interval,
            "instagram_account_id": instagram_id,
            "twitter_enabled": twitter_enabled == "true",
            "lead_webhook_url": lead_webhook,
        })
        save_config(config)
        update_env_token(page_id, page_token)
        print(f"✅ Page added: {page_id}")
    return RedirectResponse(url="/", status_code=303)


@app.post("/edit_page/{page_id}")
async def edit_page(
    page_id: str,
    edit_token: str = Form(...),
    edit_page_name: str = Form(""),
    edit_ai_provider: str = Form("gemini"),
    edit_language: str = Form("Urdu"),
    edit_brief: str = Form(""),
    edit_provider_priority: str = Form("gemini"),
    edit_posts_per_run: int = Form(2),
    edit_post_interval: int = Form(30),
    edit_instagram_id: str = Form(""),
    edit_twitter_enabled: str = Form(None),
    edit_lead_webhook: str = Form(""),
    edit_interval: int = Form(2),
    user: str = Depends(verify_auth),
):
    """Edit an existing Facebook Page."""
    config = load_config()
    new_token = None

    for p in config["pages"]:
        if p["id"] == page_id:
            new_token = edit_token
            p["token"] = new_token

            # Auto-fetch real page name
            real_name = get_facebook_page_name(p["id"], p["token"])
            if real_name:
                p["name"] = real_name
            else:
                p["name"] = edit_page_name

            p["ai_provider"] = edit_ai_provider
            p["language"] = edit_language
            p["brief"] = edit_brief
            p["interval"] = edit_interval
            p["provider_priority"] = edit_provider_priority
            p["posts_per_run"] = edit_posts_per_run
            p["post_interval"] = edit_post_interval
            p["instagram_account_id"] = edit_instagram_id
            p["twitter_enabled"] = edit_twitter_enabled == "true"
            p["lead_webhook_url"] = edit_lead_webhook
            break

    if new_token is not None:
        update_env_token(page_id, new_token)

    save_config(config)
    print(f"✅ Config saved for page {page_id}")
    return RedirectResponse(url="/", status_code=303)


@app.post("/delete_page/{page_id}")
async def delete_page(page_id: str, user: str = Depends(verify_auth)):
    """Delete a Facebook Page."""
    config = load_config()
    config["pages"] = [p for p in config["pages"] if p["id"] != page_id]
    save_config(config)
    print(f"🗑️ Deleted page {page_id}")
    return RedirectResponse(url="/", status_code=303)


@app.post("/add_url/{page_id}")
async def add_url(
    page_id: str,
    new_url: str = Form(...),
    user: str = Depends(verify_auth),
):
    """Add a source URL to a Facebook Page."""
    config = load_config()
    for p in config["pages"]:
        if p["id"] == page_id:
            if new_url and new_url not in p.get("urls", []):
                p.setdefault("urls", []).append(new_url)
                print(f"✅ Added URL to page {page_id}: {new_url}")
            break
    save_config(config)
    return RedirectResponse(url="/", status_code=303)


@app.post("/remove_url/{page_id}")
async def remove_url(
    page_id: str,
    url_to_remove: str = Form(...),
    user: str = Depends(verify_auth),
):
    """Remove a source URL from a Facebook Page."""
    config = load_config()
    for p in config["pages"]:
        if p["id"] == page_id:
            if url_to_remove in p.get("urls", []):
                p["urls"].remove(url_to_remove)
                print(f"🗑️ Removed URL from page {page_id}: {url_to_remove}")
            break
    save_config(config)
    return RedirectResponse(url="/", status_code=303)


@app.post("/update_integrations")
async def update_integrations(
    twitter_consumer_key: str = Form(""),
    twitter_consumer_secret: str = Form(""),
    twitter_access_token: str = Form(""),
    twitter_access_token_secret: str = Form(""),
    telegram_token: str = Form(""),
    authorized_users: str = Form(""),
    lead_webhook: str = Form(""),
    pinterest_client_id: str = Form(""),
    pinterest_client_secret: str = Form(""),
    pinterest_access_token: str = Form(""),
    pinterest_default_board: str = Form(""),
    user: str = Depends(verify_auth),
):
    """Saves Twitter, Telegram, Webhook, and Pinterest keys."""
    config = load_config()

    # Twitter
    config["twitter_credentials"] = {
        "consumer_key": twitter_consumer_key,
        "consumer_secret": twitter_consumer_secret,
        "access_token": twitter_access_token,
        "access_token_secret": twitter_access_token_secret,
    }

    # Telegram
    config["telegram_bot_token"] = telegram_token
    auth_users = authorized_users.strip()
    if auth_users:
        config["authorized_telegram_users"] = [
            int(x.strip()) for x in auth_users.split(",") if x.strip()
        ]
    else:
        config["authorized_telegram_users"] = []

    # Lead Webhook
    config["lead_webhook_url"] = lead_webhook

    # Pinterest
    config["pinterest_credentials"] = {
        "client_id": pinterest_client_id,
        "client_secret": pinterest_client_secret,
        "access_token": pinterest_access_token,
        "default_board": pinterest_default_board,
    }

    save_config(config)
    print("✅ Integrations updated successfully.")
    return RedirectResponse(url="/", status_code=303)


@app.post("/toggle_pause")
async def toggle_pause(user: str = Depends(verify_auth)):
    """Toggle the bot between paused and running states."""
    global BOT_PAUSED
    BOT_PAUSED = not BOT_PAUSED
    status_text = "paused" if BOT_PAUSED else "resumed"
    print(f"⏸️ Bot {status_text}")
    return RedirectResponse(url="/", status_code=303)

@app.post("/test_post/{page_id}")
async def test_post(page_id: str, user: str = Depends(verify_auth)):
    """Trigger a test post for a specific page."""
    from src.engines.engine_1_urdu_poetry import run_engine_1
    from src.engines.engine_2_deals import run_engine_2

    config = load_config()
    pages = config.get("pages", [])
    for idx, p in enumerate(pages):
        if p["id"] == page_id:
            print(f"🧪 Test Post for {page_id}...")
            if idx % 2 == 0:
                print("🔄 Using Engine 1")
                run_engine_1(p)
            else:
                print("🔄 Using Engine 2")
                run_engine_2(p)
            break
    return RedirectResponse(url="/", status_code=303)


@app.get("/analytics", response_class=HTMLResponse)
async def analytics(request: Request, user: str = Depends(verify_auth)):
    """Displays performance analytics from the CSV log."""
    import csv
    from collections import defaultdict

    log_file = "performance_log.csv"
    if not os.path.exists(log_file):
        return HTMLResponse("<h3>No analytics data yet. Run the bot and generate some posts first.</h3>")

    data = []
    with open(log_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)

    if not data:
        return HTMLResponse("<h3>No data rows found.</h3>")

    total_posts = len(data)
    avg_impressions = sum(int(d.get("impressions", 0)) for d in data) / total_posts if total_posts else 0
    avg_likes = sum(int(d.get("likes", 0)) for d in data) / total_posts if total_posts else 0
    avg_comments = sum(int(d.get("comments", 0)) for d in data) / total_posts if total_posts else 0

    page_stats = defaultdict(lambda: {"posts": 0, "impressions": 0, "likes": 0})
    for row in data:
        pid = row.get("page_id", "unknown")
        page_stats[pid]["posts"] += 1
        page_stats[pid]["impressions"] += int(row.get("impressions", 0))
        page_stats[pid]["likes"] += int(row.get("likes", 0))

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Vigil AI - Analytics</title>
        <style>
            body {{ font-family: Arial; max-width: 900px; margin: 40px auto; padding: 20px; background: #f4f7f6; }}
            .card {{ background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 20px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
            th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #eee; font-size: 13px; }}
            th {{ background: #f8f9fa; }}
            a {{ color: #007bff; text-decoration: none; }}
        </style>
    </head>
    <body>
        <a href="/">← Back to Dashboard</a>
        <div class="card" style="margin-top:20px;">
            <h2>📊 Vigil AI Performance Dashboard</h2>
            <p><strong>Total Posts Analyzed:</strong> {total_posts}</p>
            <p><strong>Avg Impressions per Post:</strong> {avg_impressions:.1f}</p>
            <p><strong>Avg Likes per Post:</strong> {avg_likes:.1f}</p>
            <p><strong>Avg Comments per Post:</strong> {avg_comments:.1f}</p>
        </div>
        <div class="card">
            <h3>📋 Breakdown by Page</h3>
            <ul>
    """
    for pid, stats in page_stats.items():
        html += f"<li><strong>Page {pid}:</strong> {stats['posts']} posts, {stats['impressions']} impressions, {stats['likes']} likes</li>"

    html += """
            </ul>
        </div>
        <div class="card">
            <h3>📝 Recent Posts (Last 10)</h3>
            <table>
                <tr><th>Time</th><th>Page</th><th>Impressions</th><th>Likes</th><th>Comments</th><th>Shares</th></tr>
    """
    for row in data[-10:]:
        html += f"<tr><td>{row.get('timestamp', '')}</td><td>{row.get('page_id', '')}</td><td>{row.get('impressions', 0)}</td><td>{row.get('likes', 0)}</td><td>{row.get('comments', 0)}</td><td>{row.get('shares', 0)}</td></tr>"

    html += """
            </table>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html)


@app.get("/affiliate", response_class=HTMLResponse)
async def affiliate_dashboard(request: Request, user: str = Depends(verify_auth)):
    """Affiliate Marketing Dashboard."""
    config = load_config()
    providers = config.get("affiliate_providers", [])
    pages = config.get("pages", [])
    all_scheduled = config.get("scheduled_affiliate_posts", [])
    scheduled = [p for p in all_scheduled if not p.get("posted", False)]

    return templates.TemplateResponse(
        request=request,
        name="affiliate.html",
        context={
            "providers": providers,
            "pages": pages,
            "scheduled_posts": scheduled,
            "search_results": None,
            "current_page_id": "",
            "current_provider": "",
            "default_time": "",
            "search_term": "",
            "message": "🔗 Affiliate Marketing Dashboard",
        }
    )


@app.post("/add_provider")
async def add_provider(
    provider_name: str = Form(""),
    api_key: str = Form(""),
    api_secret: str = Form(""),
    associate_tag: str = Form(""),
    user: str = Depends(verify_auth),
):
    """Add a new affiliate provider."""
    config = load_config()
    if "affiliate_providers" not in config:
        config["affiliate_providers"] = []

    provider_id = str(uuid.uuid4())[:8]
    provider_name_lower = provider_name.strip().lower()

    # Load drivers
    drivers = load_drivers()

    if provider_name_lower in drivers:
        provider_config = drivers[provider_name_lower].copy()
        print(f"✅ Driver found for '{provider_name_lower}'")
    else:
        print(f"⚠️ No driver found for '{provider_name_lower}'. Saving basic config.")
        provider_config = {}

    # Inject user credentials
    provider_config["api_key"] = api_key.strip()
    provider_config["api_secret"] = api_secret.strip()
    provider_config["associate_tag"] = associate_tag.strip()

    # Replace placeholders in headers, static_params, body_data
    if "headers" in provider_config:
        for key, value in list(provider_config["headers"].items()):
            if isinstance(value, str):
                provider_config["headers"][key] = (
                    value.replace("{{api_secret}}", api_secret.strip())
                         .replace("{{api_key}}", api_key.strip())
                )

    if "static_params" in provider_config:
        for key, value in list(provider_config["static_params"].items()):
            if isinstance(value, str):
                provider_config["static_params"][key] = (
                    value.replace("{{associate_tag}}", associate_tag.strip())
                         .replace("{{api_key}}", api_key.strip())
                )

    if "body_data" in provider_config:
        for key, value in list(provider_config["body_data"].items()):
            if isinstance(value, str):
                provider_config["body_data"][key] = (
                    value.replace("{{associate_tag}}", associate_tag.strip())
                         .replace("{{api_key}}", api_key.strip())
                )

    new_provider = {
        "id": provider_id,
        "provider_type": provider_name_lower,
        "nickname": provider_name.strip(),
        **provider_config,
    }

    config["affiliate_providers"].append(new_provider)
    save_config(config)
    print(f"✅ Provider '{provider_name_lower}' saved successfully.")
    return RedirectResponse(url="/affiliate", status_code=303)


@app.post("/delete_provider/{provider_id}")
async def delete_provider(provider_id: str, user: str = Depends(verify_auth)):
    """Delete an affiliate provider."""
    config = load_config()
    config["affiliate_providers"] = [
        p for p in config.get("affiliate_providers", []) if p["id"] != provider_id
    ]
    save_config(config)
    print(f"🗑️ Deleted provider {provider_id}")
    return RedirectResponse(url="/affiliate", status_code=303)


@app.post("/search_products")
async def search_products(
    page_id: str = Form(...),
    provider_name: str = Form(...),
    search_term: str = Form(...),
    user: str = Depends(verify_auth),
):
    """Handle the search form → redirect to paginated GET route."""
    return RedirectResponse(
        url=f"/affiliate_search?page_id={page_id}&provider_name={provider_name}&search_term={search_term}&page_no=1",
        status_code=303,
    )
@app.get("/affiliate_search", response_class=HTMLResponse)
async def affiliate_search(
    request: Request,
    page_id: str,
    provider_name: str,
    search_term: str,
    page_no: int = 1,
    user: str = Depends(verify_auth),
):
    """Fetch products for a specific page number and render results."""
    import concurrent.futures
    from src.utils.affiliate_api import search_products as search_products_api
    from datetime import datetime as dt

    config = load_config()

    # Find the provider
    provider = None
    for p in config.get("affiliate_providers", []):
        if p["nickname"] == provider_name or p["provider_type"] == provider_name:
            provider = p
            break

    if not provider:
        return HTMLResponse("<h3>❌ Provider not found</h3><a href='/affiliate'>← Back</a>")

    # Fetch products for the requested page
    products = search_products_api(provider, search_term, page_no=page_no)

    # Enrich with video status (parallel)
    def enrich_product(product):
        video_url = fetch_video_from_product_page(product.get("product_url", ""))
        product["has_video"] = bool(video_url)
        product["video_url"] = video_url
        return product

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        enriched_products = list(executor.map(enrich_product, products))

    # Determine if more pages exist
    has_more = len(products) == 15  # Full page returned = likely more

    # Filter out already-scheduled products
    all_scheduled = config.get("scheduled_affiliate_posts", [])
    scheduled_ids = [p.get("product_id") for p in all_scheduled if p.get("product_id")]
    enriched_products = [p for p in enriched_products if p.get("product_id") not in scheduled_ids]

    # Prepare context
    providers = config.get("affiliate_providers", [])
    pages = config.get("pages", [])
    scheduled = [p for p in all_scheduled if not p.get("posted", False)]
    default_time = (dt.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")

    return templates.TemplateResponse(
        request=request,
        name="affiliate.html",
        context={
            "providers": providers,
            "pages": pages,
            "scheduled_posts": scheduled,
            "search_results": enriched_products,
            "current_page_id": page_id,
            "current_provider": provider_name,
            "default_time": default_time,
            "search_term": search_term,
            "page_no": page_no,
            "has_more": has_more,
            "message": "🔗 Affiliate Marketing Dashboard",
        }
    )


@app.post("/schedule_affiliate_posts")
async def schedule_affiliate_posts(
    request: Request,
    user: str = Depends(verify_auth),
):
    """Schedule a specific product — reads data directly from the form (no re-fetch)."""
    from datetime import datetime as dt

    config = load_config()
    if "scheduled_affiliate_posts" not in config:
        config["scheduled_affiliate_posts"] = []

    form = await request.form()

    # ---- Context ----
    page_id = form.get("page_id")
    provider_name = form.get("provider_name")
    search_term = form.get("search_term")
    page_no = form.get("page_no", "1")

    # ---- Product data (each product has its own form) ----
    product_id = form.get("product_id", "")
    product_name = form.get("product_name", search_term)
    product_image = form.get("product_image", "")
    product_url = form.get("product_url", "")
    affiliate_link = form.get("product_affiliate_link", "")
    sale_usd = form.get("product_sale_usd", "")
    original_usd = form.get("product_original_usd", "")
    currency = form.get("product_currency", "USD")

    # ---- User input ----
    description = form.get("desc", "")
    scheduled_time_str = form.get("time", "")
    video_url = form.get("video_url", "")

    # ---- Debug log ----
    print("📥 Schedule request received:")
    print(f"   product_id   = {product_id}")
    print(f"   product_name = {product_name[:60] if product_name else '(empty)'}")
    print(f"   page_id      = {page_id}")
    print(f"   time         = {scheduled_time_str}")
    print(f"   video_url    = {video_url[:60] if video_url else '(none)'}")

    if not scheduled_time_str:
        return HTMLResponse("<h3>❌ Scheduled time is required</h3><a href='/affiliate'>← Back</a>")

    # ---- Convert PKT to UTC ----
    local_tz = pytz.timezone("Asia/Karachi")
    local_time = dt.strptime(scheduled_time_str, "%Y-%m-%dT%H:%M")
    local_time = local_tz.localize(local_time)
    utc_time = local_time.astimezone(pytz.UTC)
    scheduled_time_utc = utc_time.strftime("%Y-%m-%dT%H:%M")

    # ---- Create scheduled post ----
    new_post = {
        "id": str(uuid.uuid4())[:8],
        "page_id": page_id,
        "provider_name": provider_name,
        "search_term": search_term,
        "product_id": product_id,
        "product_name": product_name,
        "product_image": product_image,
        "product_url": product_url,
        "affiliate_link": affiliate_link,
        "sale_price_usd": sale_usd,
        "original_price_usd": original_usd,
        "currency_usd": currency,
        "description_override": description,
        "scheduled_time": scheduled_time_utc,
        "posted": False,
        "fb_post_id": None,
        "video_url": video_url,
        "has_video": bool(video_url),
    }
    config["scheduled_affiliate_posts"].append(new_post)
    save_config(config)

    print(f"✅ Scheduled successfully: {product_name[:50]}")

    # ---- Redirect back to the same search results page ----
    return RedirectResponse(
        url=f"/affiliate_search?page_id={page_id}&provider_name={provider_name}&search_term={search_term}&page_no={page_no}",
        status_code=303,
    )


@app.post("/cancel_scheduled/{post_id}")
async def cancel_scheduled(post_id: str, user: str = Depends(verify_auth)):
    """Cancel a scheduled affiliate post."""
    config = load_config()
    config["scheduled_affiliate_posts"] = [
        p for p in config.get("scheduled_affiliate_posts", []) if p["id"] != post_id
    ]
    save_config(config)
    print(f"🗑️ Cancelled scheduled post {post_id}")
    return RedirectResponse(url="/affiliate", status_code=303)


@app.get("/health")
async def health():
    """Simple health check endpoint."""
    return {"status": "ok", "message": "Vigil AI Plus is alive"}


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":
    import uvicorn
    import webbrowser
    import threading
    import time

    def open_browser():
        time.sleep(3)
        webbrowser.open("http://127.0.0.1:8000")

    threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)