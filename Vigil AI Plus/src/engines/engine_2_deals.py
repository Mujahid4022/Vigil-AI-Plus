"""
engine_2_deals.py - Universal Engine 2 (Load Balancer Worker 2)

This engine is a twin of Engine 1. It is completely universal.
Images are generated using Gemini Imagen (Nano Banana) with a fallback to Pollinations.ai.
Urdu text is proofread by AI before posting.
"""

import os
import time
import json
import csv
import requests
import tempfile
from bs4 import BeautifulSoup
from config.config import get_api_key, get_model_name

# --- AI SDK Imports ---
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

try:
    from mistralai import Mistral
except ImportError:
    Mistral = None

# --- Import Facebook client helpers ---
from src.core.facebook_client import (
    post_to_facebook,
    post_video_to_facebook,
    get_post_insights,
    add_utm_parameters,
    post_to_instagram,
)


# ----------------------------------------------------------------------
# Helper: Scrape URL
# ----------------------------------------------------------------------
def scrape_url(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, timeout=15, headers=headers)
        soup = BeautifulSoup(resp.text, "html.parser")
        text = " ".join([p.get_text() for p in soup.find_all("p")])[:4000]
        return text.strip() or "No content."
    except Exception as e:
        return f"Error: {e}"


# ----------------------------------------------------------------------
# Helper: Generate Image using Gemini Imagen (Nano Banana)
# ----------------------------------------------------------------------
def generate_image(image_prompt, gemini_key):
    if not genai or not types or not gemini_key:
        print("❌ Gemini SDK/types or key not available for Imagen.")
        return None

    IMAGEN_MODEL_FALLBACKS = [
        "models/gemini-3.1-flash-image",
        "models/gemini-3.1-flash-lite-image",
        "models/gemini-3-pro-image",
    ]

    client = genai.Client(api_key=gemini_key)
    for model_name in IMAGEN_MODEL_FALLBACKS:
        try:
            print(f"🎨 Trying Nano Banana model: {model_name}...")
            response = client.models.generate_content(
                model=model_name,
                contents=image_prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["image"],
                ),
            )
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.mime_type.startswith(
                        "image/"
                    ):
                        print(f"✅ Image generated successfully with {model_name}.")
                        return part.inline_data.data
            print(f"❌ {model_name} returned no image data. Trying next...")
        except Exception as e:
            print(f"❌ {model_name} failed: {e}. Trying next...")

    print("❌ All Nano Banana fallback models failed.")
    return None


# ----------------------------------------------------------------------
# Helper: Generate Image (Pollinations.ai - Fallback)
# ----------------------------------------------------------------------
def generate_pollinations_image(prompt):
    try:
        print("🎨 Falling back to Pollinations.ai...")
        url = f"https://image.pollinations.ai/prompt/{prompt}"
        response = requests.get(url, timeout=45)
        if response.status_code == 200:
            # Check that the response is actually an image
            content_type = response.headers.get('content-type', '')
            if 'image' in content_type:
                return response.content
            else:
                print(f"❌ Pollinations returned {content_type}, not an image. Skipping.")
                return None
        else:
            print(f"❌ Pollinations request failed: {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ Pollinations error: {e}")
        return None

# ----------------------------------------------------------------------
# Helper: Generate Image using Agnes AI (Free, unlimited, 4K)
# ----------------------------------------------------------------------
def generate_agnes_image(prompt, api_key):
    """
    Generate an image using Agnes AI's OpenAI‑compatible API.
    Returns a dict with 'url' (public URL) and 'bytes' (image bytes).
    Returns None if both are unavailable.
    """
    import requests
    import base64

    # --- Agnes model list (in order of preference) ---
    models = [
        "agnes-image-2.5-flash",
        "agnes-image-2.1-flash",
        "agnes-image-2.0-flash"
    ]

    url = "https://apihub.agnes-ai.com/v1/images/generations"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    for model in models:
        print(f"🎨 Trying Agnes model: {model}")
        payload = {
            "model": model,
            "prompt": prompt,
            "size": "1024x1024",          # or "1024x768", "1K", etc.
            "return_base64": True
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=60)
            print(f"🔍 Agnes API status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                # Get the public URL (if available)
                image_url = data.get("data", [{}])[0].get("url")
                # Get Base64 data
                b64_image = data.get("data", [{}])[0].get("b64_json")
                image_bytes = None
                if b64_image:
                    image_bytes = base64.b64decode(b64_image)

                if image_url or image_bytes:
                    print(f"✅ Agnes {model} succeeded")
                    return {"url": image_url, "bytes": image_bytes}
                else:
                    print(f"❌ No image data or URL for {model}. Trying next...")
            else:
                print(f"❌ Agnes {model} error: {response.status_code}")
                print(f"   Response: {response.text[:200]}...")
        except Exception as e:
            print(f"❌ Agnes {model} exception: {e}. Trying next...")

    print("❌ All Agnes models failed.")
    return None

# ----------------------------------------------------------------------
# Helper: Get Facebook Public Image URL from Post ID
# ----------------------------------------------------------------------
def get_facebook_image_url(post_id, access_token):
    """
    Fetch the public image URL from a Facebook post or photo.
    Tries: photo source → full_picture → attachments.
    """
    try:
        # Approach 1: Try to fetch as a photo (since we upload via /photos)
        photo_url = f"https://graph.facebook.com/v26.0/{post_id}?fields=source,images&access_token={access_token}"
        resp = requests.get(photo_url, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            # Check for direct source URL
            source = data.get("source")
            if source:
                print(f"✅ Found photo source URL: {source[:60]}...")
                return source
            # Check for images array (first image)
            images = data.get("images", [])
            if images and isinstance(images, list) and len(images) > 0:
                src = images[0].get("source")
                if src:
                    print(f"✅ Found photo image URL: {src[:60]}...")
                    return src
        
        # Approach 2: Try full_picture (works for feed posts)
        feed_url = f"https://graph.facebook.com/v26.0/{post_id}?fields=full_picture,picture&access_token={access_token}"
        resp = requests.get(feed_url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            full_picture = data.get("full_picture")
            if full_picture:
                print(f"✅ Found full_picture: {full_picture[:60]}...")
                return full_picture
            picture = data.get("picture", {}).get("data", {}).get("url")
            if picture:
                print(f"✅ Found picture URL: {picture[:60]}...")
                return picture
        
        # Approach 3: Try attachments (fallback)
        att_url = f"https://graph.facebook.com/v26.0/{post_id}?fields=attachments&access_token={access_token}"
        resp = requests.get(att_url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            attachments = data.get("attachments", {}).get("data", [])
            if attachments:
                img = attachments[0].get("media", {}).get("image", {}).get("src")
                if img:
                    print(f"✅ Found attachment image: {img[:60]}...")
                    return img
                target = attachments[0].get("target", {}).get("url")
                if target:
                    print(f"✅ Found attachment target: {target[:60]}...")
                    return target
        
        # If all fail, log the raw responses for debugging
        print("⚠️ Could not retrieve Facebook image URL from any field.")
        return None
        
    except Exception as e:
        print(f"⚠️ Error fetching Facebook image URL: {e}")
        return None


# ----------------------------------------------------------------------
# Helper: Proofread Urdu Text using the AI itself
# ----------------------------------------------------------------------
def proofread_text(text, page):
    """
    Sends the generated text back to the AI for proofreading.
    Fixes grammar, spelling, and punctuation WITHOUT changing meaning.
    """
    language = page.get("language", "English")

    # Only proofread if language is Urdu
    if language != "Urdu":
        return text

    print("📝 Proofreading Urdu text for grammar mistakes...")

    # Build a strict proofreading prompt
    proofread_prompt = f"""You are a strict Urdu grammar editor. Proofread the following Urdu text.
Rules:
1. Fix ONLY spelling mistakes, grammar errors, and punctuation.
2. Do NOT change the meaning, style, or theme.
3. Do NOT add or remove any lines.
4. Do NOT add any explanations or notes.
5. Only return the final corrected text.

Text to proofread:
{text}

Corrected text:"""

    # Use the same provider priority list from the page
    priority_list = page.get("provider_priority", "gemini").split(",")
    priority_list = [p.strip() for p in priority_list if p.strip()]

    for provider in priority_list:
        api_key = get_api_key(provider)
        if not api_key:
            continue
        try:
            if provider == "groq":
                if not Groq:
                    continue
                model = get_model_name("groq") or "openai/gpt-oss-120b"
                client = Groq(api_key=api_key)
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": proofread_prompt}],
                )
                corrected = response.choices[0].message.content.strip()
                print(f"✅ Proofreading successful using {provider}")
                return corrected
            else:  # Gemini (or fallback)
                if not genai:
                    continue
                model = get_model_name("gemini") or "models/gemini-3.5-flash"
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model=model, contents=proofread_prompt
                )
                corrected = response.text.strip()
                print(f"✅ Proofreading successful using {provider}")
                return corrected
        except Exception as e:
            print(f"⚠️ Proofreading with {provider} failed: {e}. Trying next...")
            continue

    # If all proofreading fails, return the original text
    print("⚠️ Proofreading failed. Posting original text.")
    return text


# ----------------------------------------------------------------------
# Helper: Log Post Performance
# ----------------------------------------------------------------------
def log_performance(post_id, insights, page_id):
    """
    Logs post insights to a CSV file for later analysis.
    """
    if not insights:
        return

    log_file = "performance_log.csv"
    file_exists = os.path.isfile(log_file)
    with open(log_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(
                [
                    "timestamp",
                    "page_id",
                    "post_id",
                    "impressions",
                    "engaged_users",
                    "clicks",
                    "likes",
                    "comments",
                    "shares",
                ]
            )
        writer.writerow(
            [
                time.strftime("%Y-%m-%d %H:%M:%S"),
                page_id,
                post_id,
                insights.get("post_impressions", 0),
                insights.get("post_engaged_users", 0),
                insights.get("post_clicks", 0),
                insights.get("post_like_count", 0),
                insights.get("post_comment_count", 0),
                insights.get("post_share_count", 0),
            ]
        )
        print(f"📊 Performance logged for post {post_id}")


# ----------------------------------------------------------------------
# MAIN ENGINE 2
# ----------------------------------------------------------------------
def run_engine_2(page):
    """
    Universal Engine 2.
    Generates text, proofreads it, then posts with Gemini Imagen -> Pollinations fallback.
    Also detects video URLs and posts them as videos.
    """
    print(f"🤖 [Engine 2] Running for Page: {page['id']}")

    # --- Load config ---
    CONFIG_FILE = "config.json"
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
    else:
        config = {}

    target_urls = page.get("urls", [])
    posts_per_run = page.get("posts_per_run", 2)
    post_interval = page.get("post_interval", 30)
    language = page.get("language", "English")
    priority_list = page.get("provider_priority", "gemini").split(",")
    priority_list = [p.strip() for p in priority_list if p.strip()]



    target_urls = list(set(target_urls))

    # ------------------------------------------------------------------
    # CHECK IF THE BRIEF REQUIRES SCRAPING (SALES, DEALS, ETC.)
    # ------------------------------------------------------------------
    scrape_keywords = [
        "sale",
        "deal",
        "scrape",
        "find",
        "latest",
        "promotion",
        "discount",
        "offer",
        "price",
        "shop",
        "product",
        "price drop",
    ]
    brief_lower = page.get("brief", "").lower()
    requires_scraping = any(keyword in brief_lower for keyword in scrape_keywords)


    # ----------------------------------------------------------
    # SAFE SCENARIO 1: NO URLs (but brief is safe - poetry, quotes, etc.)
    # ----------------------------------------------------------
    if not target_urls:
        print(
            "ℹ️ No URLs provided. Generating content based purely on the Brief (safe topic)."
        )
        urls_to_process = [None]
        posts_per_run = 1

    # ----------------------------------------------------------
    # SAFE SCENARIO 2: URLs exist (or Google Search is configured)
    # ----------------------------------------------------------
    else:
        max_posts = min(len(target_urls), posts_per_run)
        urls_to_process = target_urls[:max_posts]
        print(f"📋 Processing up to {len(urls_to_process)} URLs")

    posts_made = 0

    for idx, url in enumerate(urls_to_process):
        # --------------------------------------------
        # CHECK IF IT'S A VIDEO URL
        # --------------------------------------------
        video_extensions = [".mp4", ".mov", ".avi", ".mkv", ".webm"]
        is_video = any(url.lower().endswith(ext) for ext in video_extensions) if url else False

        if is_video:
            print(f"🎬 Detected video URL: {url}")
            # For video, we generate text first (using the brief) but then post as video
            # We need to generate the caption
            # We'll reuse the text generation logic but without image generation.

            # Build prompt for caption
            lang_instruction = ""
            if language == "Urdu":
                lang_instruction = "Write a caption for this video post in Urdu (Nastaleeq style). Use emojis."
            elif language == "English":
                lang_instruction = "Write a caption for this video post in English. Use emojis."
            elif language == "Both":
                lang_instruction = "Write the caption in both Urdu and English (side by side). Use emojis."
            else:
                lang_instruction = "Write the caption in the language that best fits the topic. Use emojis."

            # Build prompt (no scraped data)
            prompt = f"{lang_instruction}\n\nContext/Brief: {page['brief']}\n\nWrite only the caption text, nothing else."

            # Get caption via AI
            formatted_post = None
            for provider in priority_list:
                api_key = get_api_key(provider)
                if not api_key:
                    continue
                try:
                    if provider == "groq":
                        if not Groq:
                            continue
                        model = get_model_name("groq") or "openai/gpt-oss-120b"
                        client = Groq(api_key=api_key)
                        response = client.chat.completions.create(
                            model=model,
                            messages=[{"role": "user", "content": prompt}],
                        )
                        formatted_post = response.choices[0].message.content
                        break
                    elif provider == "openai":
                        if not OpenAI:
                            continue
                        model = get_model_name("openai") or "gpt-4o"
                        client = OpenAI(api_key=api_key)
                        response = client.chat.completions.create(
                            model=model,
                            messages=[{"role": "user", "content": prompt}],
                        )
                        formatted_post = response.choices[0].message.content
                        break
                    elif provider == "deepseek":
                        if not OpenAI:
                            continue
                        model = get_model_name("deepseek") or "deepseek-chat"
                        client = OpenAI(
                            api_key=api_key, base_url="https://api.deepseek.com"
                        )
                        response = client.chat.completions.create(
                            model=model,
                            messages=[{"role": "user", "content": prompt}],
                        )
                        formatted_post = response.choices[0].message.content
                        break
                    elif provider == "anthropic":
                        if not Anthropic:
                            continue
                        model = get_model_name("anthropic") or "claude-sonnet-5"
                        client = Anthropic(api_key=api_key)
                        response = client.messages.create(
                            model=model,
                            max_tokens=1024,
                            messages=[{"role": "user", "content": prompt}],
                        )
                        formatted_post = response.content[0].text
                        break
                    elif provider == "mistral":
                        if not Mistral:
                            continue
                        model = get_model_name("mistral") or "mistral-medium-2508"
                        client = Mistral(api_key=api_key)
                        response = client.chat.complete(
                            model=model,
                            messages=[{"role": "user", "content": prompt}],
                        )
                        formatted_post = response.choices[0].message.content
                        break
                    else:  # Gemini
                        if not genai:
                            continue
                        model = get_model_name("gemini") or "models/gemini-3.5-flash"
                        client = genai.Client(api_key=api_key)
                        response = client.models.generate_content(
                            model=model, contents=prompt
                        )
                        formatted_post = response.text.strip()
                        break
                except Exception as e:
                    print(f"❌ {provider} failed for video caption: {e}")
                    continue

            if not formatted_post:
                print("❌ Failed to generate caption for video.")
                continue

            # Proofread if Urdu
            formatted_post = proofread_text(formatted_post, page)

            # Post the video
            video_post_id = post_video_to_facebook(
                page_id=page["id"],
                access_token=page["token"],
                caption=formatted_post,
                video_url=url,
            )

            if video_post_id:
                posts_made += 1
                # Log performance
                insights = get_post_insights(video_post_id, page["token"])
                if insights:
                    log_performance(video_post_id, insights, page["id"])
                # Wait before next post
                if idx < len(urls_to_process) - 1:
                    time.sleep(post_interval)
            continue  # Skip the rest of the loop for video

        # --------------------------------------------
        # NORMAL FLOW: Not a video – scrape & post text+image
        # --------------------------------------------
        if url:
            print(f"📡 Scraping: {url}")
            scraped_text = scrape_url(url)
            if "Error" in scraped_text:
                continue
        else:
            print("📝 No URL provided. Using Brief only for content.")
            scraped_text = ""

        # --- Language instruction ---
        lang_instruction = ""
        if language == "Urdu":
            lang_instruction = "Write the post exclusively in Urdu (Nastaleeq style). Use emojis."
        elif language == "English":
            lang_instruction = "Write the post exclusively in English. Use emojis."
        elif language == "Both":
            lang_instruction = "Write the post in both Urdu and English (side by side). Use emojis."
        else:
            lang_instruction = "Write the post in the language that best fits the topic. Use emojis."

        # ---- Dynamic rotation based on Brief ----
        brief = page.get("brief", "")
        rotation_prefix = "ROTATION_LIST:"
        rotation_instruction = ""
        if rotation_prefix in brief:
            list_str = brief.split(rotation_prefix)[1].split("\n")[0].strip()
            rotation_items = [item.strip() for item in list_str.split(",") if item.strip()]
            if rotation_items:
                idx = config.get("rotation_index", 0)
                current_item = rotation_items[idx % len(rotation_items)]
                config["rotation_index"] = (idx + 1) % len(rotation_items)
                with open(CONFIG_FILE, "w") as f:
                    json.dump(config, f, indent=4)
                print(f"🔄 Rotation item: {current_item}")
                print(f"🔄 DEBUG: current_item='{current_item}', new_index={config['rotation_index']}")
                rotation_instruction = f"Write a post specifically about: {current_item}.\n\n"

        # --- Build prompt ---
        if scraped_text:
            prompt = f"{rotation_instruction}{lang_instruction}\n\nContext/Brief: {page['brief']}\n\nScraped Data: {scraped_text}\n\nAlso, return a separate, single sentence in ENGLISH describing an image that represents this text, starting with 'IMAGE_PROMPT:'"
        else:
            prompt = f"{rotation_instruction}{lang_instruction}\n\nContext/Brief: {page['brief']}\n\nAlso, return a separate, single sentence in ENGLISH describing an image that represents this text, starting with 'IMAGE_PROMPT:'"

        formatted_post = None
        image_prompt = None

        # --- AI Provider Loop (Text Generation) ---
        for provider in priority_list:
            api_key = get_api_key(provider)
            if not api_key:
                print(f"⏭️ No key for {provider}, skipping...")
                continue
            try:
                if provider == "groq":
                    if not Groq:
                        raise Exception("Groq library missing.")
                    model = get_model_name("groq") or "openai/gpt-oss-120b"
                    client = Groq(api_key=api_key)
                    print(f"🧠 Trying Groq ({model})...")
                    response = client.chat.completions.create(
                        model=model, messages=[{"role": "user", "content": prompt}]
                    )
                    formatted_post = response.choices[0].message.content
                    print(f"✅ Successfully used {provider}")
                    break
                elif provider == "openai":
                    if not OpenAI:
                        raise Exception("OpenAI library missing.")
                    model = get_model_name("openai") or "gpt-4o"
                    client = OpenAI(api_key=api_key)
                    print(f"🧠 Trying OpenAI ({model})...")
                    response = client.chat.completions.create(
                        model=model, messages=[{"role": "user", "content": prompt}]
                    )
                    formatted_post = response.choices[0].message.content
                    print(f"✅ Successfully used {provider}")
                    break
                elif provider == "deepseek":
                    if not OpenAI:
                        raise Exception("OpenAI library missing.")
                    model = get_model_name("deepseek") or "deepseek-chat"
                    client = OpenAI(
                        api_key=api_key, base_url="https://api.deepseek.com"
                    )
                    print(f"🧠 Trying DeepSeek ({model})...")
                    response = client.chat.completions.create(
                        model=model, messages=[{"role": "user", "content": prompt}]
                    )
                    formatted_post = response.choices[0].message.content
                    print(f"✅ Successfully used {provider}")
                    break
                elif provider == "anthropic":
                    if not Anthropic:
                        raise Exception("Anthropic library missing.")
                    model = get_model_name("anthropic") or "claude-sonnet-5"
                    client = Anthropic(api_key=api_key)
                    print(f"🧠 Trying Anthropic ({model})...")
                    response = client.messages.create(
                        model=model,
                        max_tokens=1024,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    formatted_post = response.content[0].text
                    print(f"✅ Successfully used {provider}")
                    break
                elif provider == "mistral":
                    if not Mistral:
                        raise Exception("Mistral library missing.")
                    model = get_model_name("mistral") or "mistral-medium-2508"
                    client = Mistral(api_key=api_key)
                    print(f"🧠 Trying Mistral ({model})...")
                    response = client.chat.complete(
                        model=model, messages=[{"role": "user", "content": prompt}]
                    )
                    formatted_post = response.choices[0].message.content
                    print(f"✅ Successfully used {provider}")
                    break
                else:  # Gemini
                    if not genai:
                        raise Exception("Genai library missing.")
                    model = get_model_name("gemini") or "models/gemini-3.5-flash"
                    client = genai.Client(api_key=api_key)
                    print(f"🧠 Trying Gemini ({model})...")
                    response = client.models.generate_content(
                        model=model, contents=prompt
                    )
                    formatted_post = response.text.strip()
                    print(f"✅ Successfully used {provider}")
                    break
            except Exception as e:
                print(f"❌ {provider} failed: {e}, trying next...")
                continue

        if not formatted_post:
            print(f"❌ All providers failed for {'URL' if url else 'brief-only'}.")
            continue

        # --- Extract Image Prompt & Clean Text ---
        if formatted_post and "IMAGE_PROMPT:" in formatted_post:
            parts = formatted_post.split("IMAGE_PROMPT:")
            formatted_post = parts[0].strip()
            formatted_post = formatted_post.replace("**", "")  # Remove Markdown
            image_prompt = parts[1].strip()
        else:
            image_prompt = page["brief"] or "A beautiful stock photo"
            if scraped_text:
                image_prompt = scraped_text[:200]

        # --- PROOFREADING (Only for Urdu) ---
        formatted_post = proofread_text(formatted_post, page)

        # ------------------------------------------------------------------
        # CHECK THE BRIEF: SKIP IMAGE?
        # ------------------------------------------------------------------
        skip_image = False
        brief_lower = page.get("brief", "").lower()
        if (
            "no image" in brief_lower
            or "text only" in brief_lower
            or "only text" in brief_lower
        ):
            skip_image = True
            print("ℹ️ Brief says 'no image'. Skipping image generation.")
        else:
            print("ℹ️ Brief has no image restriction.")

        # ------------------------------------------------------------------
        # GENERATE IMAGE: Agnes AI -> Gemini -> Pollinations.ai
        # ------------------------------------------------------------------
        agnes_result = None
        image_bytes = None
        if not skip_image:
            # Try Agnes AI first (free, unlimited, 4K)
            agnes_key = config.get("agnes_api", {}).get("key")
            if agnes_key:
                print("🎨 Trying Agnes AI (free 4K)...")
                agnes_result = generate_agnes_image(image_prompt, agnes_key)
                if agnes_result:
                    # If we have image bytes
                    if agnes_result.get("bytes"):
                        image_bytes = agnes_result["bytes"]
                        print("✅ Agnes AI image bytes received.")
                    # If we only have a URL (no bytes), download it
                    elif agnes_result.get("url"):
                        print(f"📸 Agnes returned URL: {agnes_result['url'][:60]}...")
                        try:
                            import requests
                            resp = requests.get(agnes_result["url"], timeout=30)
                            if resp.status_code == 200:
                                image_bytes = resp.content
                                print("✅ Agnes AI image downloaded from URL.")
                            else:
                                print(f"❌ Failed to download Agnes URL: {resp.status_code}")
                                image_bytes = None
                        except Exception as e:
                            print(f"⚠️ Could not download Agnes URL: {e}")
                            image_bytes = None
                    else:
                        print("❌ Agnes returned no data.")
                        agnes_result = None
                else:
                    print("❌ Agnes failed (no result).")
            
            # If Agnes fails or didn't produce bytes, try Gemini
            if not image_bytes:
                gemini_key = get_api_key("gemini")
                if gemini_key:
                    print("🎨 Trying Gemini Imagen (Nano Banana)...")
                    image_bytes = generate_image(image_prompt, gemini_key)
            
            # If Gemini fails, fallback to Pollinations.ai
            if not image_bytes:
                print("⚠️ Gemini failed or unavailable. Falling back to Pollinations.ai...")
                image_bytes = generate_pollinations_image(image_prompt)

        # ------------------------------------------------------------------
        # SAVE IMAGE TO TEMP FILE & POST
        # ------------------------------------------------------------------
        temp_image_path = None
        if image_bytes:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(image_bytes)
                temp_image_path = tmp.name

        # Call the correct function signature (returns post ID)
        post_id = post_to_facebook(
            access_token=page["token"],
            page_id=page["id"],
            message=formatted_post,
            image_path=temp_image_path,
        )

        # ------------------------------------------------------------------
        # LOG PERFORMANCE IF POST SUCCEEDED
        # ------------------------------------------------------------------
        if page.get("approval_required", False):
            # ---- SAVE AS DRAFT instead of posting ----
            import uuid as _uuid
            import shutil
            draft_id = str(_uuid.uuid4())[:8]

            # Save image to persistent folder
            PENDING_DIR = os.path.join("data", "pending")
            os.makedirs(PENDING_DIR, exist_ok=True)
            pending_image = os.path.join(PENDING_DIR, f"{draft_id}.jpg")

            if temp_image_path and os.path.exists(temp_image_path):
                shutil.copy(temp_image_path, pending_image)

            # Add to config
            CONFIG_FILE_LOCAL = "config.json"
            with open(CONFIG_FILE_LOCAL, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if "pending_approvals" not in cfg:
                cfg["pending_approvals"] = []
            cfg["pending_approvals"].append({
                "id": draft_id,
                "page_id": page["id"],
                "caption": formatted_post,
                "image_path": pending_image if os.path.exists(pending_image) else None,
                "video_url": "",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            with open(CONFIG_FILE_LOCAL, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4)

            # Notify Telegram
            try:
                from src.core.telegram_bot import send_draft_notification
                import asyncio
                asyncio.run_coroutine_threadsafe(
                    send_draft_notification(
                        post_id=draft_id,
                        page_name=page.get("name", page["id"]),
                        caption=formatted_post,
                        image_path=pending_image if os.path.exists(pending_image) else None,
                    ),
                    asyncio.get_event_loop(),
                )
            except Exception as e:
                print(f"⚠️ Could not notify Telegram: {e}")

            print(f"📤 Draft {draft_id} saved, waiting for approval.")

            # Cleanup temp image
            if temp_image_path and os.path.exists(temp_image_path):
                os.remove(temp_image_path)

            continue  # Skip Facebook posting

        else:
            # ---- POST DIRECTLY (no approval needed) ----
            if post_id:
                posts_made += 1
                insights = get_post_insights(post_id, page["token"])
                if insights:
                    log_performance(post_id, insights, page["id"])
                if idx < len(urls_to_process) - 1:
                    time.sleep(post_interval)

        # --------------------------------------------------------------
        # CROSS-POSTING & LEAD TRACKING (Twitter, Instagram, Webhooks)
        # --------------------------------------------------------------

        # ---- Cross-Posting to Twitter (Per Page) ----
        try:
            from src.core.twitter_client import post_to_twitter
            
            # Check if Twitter is enabled for this page AND global keys exist
            twitter_enabled = page.get("twitter_enabled", False)
            global_keys = config.get("twitter_credentials", {})
            consumer_key = global_keys.get("consumer_key")
            consumer_secret = global_keys.get("consumer_secret")
            access_token = global_keys.get("access_token")
            access_token_secret = global_keys.get("access_token_secret")
            
            if twitter_enabled and consumer_key and consumer_secret and access_token and access_token_secret:
                tweet_text = formatted_post[:280]
                tweet_id = post_to_twitter(
                    consumer_key=consumer_key,
                    consumer_secret=consumer_secret,
                    access_token=access_token,
                    access_token_secret=access_token_secret,
                    text=tweet_text,
                    image_path=temp_image_path
                )
                if tweet_id:
                    print(f"🐦 Cross-posted to Twitter: {tweet_id}")
            elif twitter_enabled:
                print("⚠️ Twitter is enabled for this page but global keys are missing. Please add them in Integrations.")
        except Exception as e:
            print(f"⚠️ Twitter cross-post failed: {e}")

        # ---- Cross-Posting to Instagram ----
        instagram_id = page.get("instagram_account_id")
        if instagram_id:
            try:
                from src.core.facebook_client import post_to_instagram
                import requests  # for Graph API call

                ig_image = None
                ig_image_type = None  # 'url' only

                # 1. Use Agnes public URL if available
                if agnes_result and agnes_result.get("url"):
                    ig_image = agnes_result["url"]
                    ig_image_type = 'url'
                    print(f"📸 Instagram: Using Agnes public URL: {ig_image[:60]}...")
                # 2. If we have a local file, get its public URL from Facebook
                elif temp_image_path and os.path.exists(temp_image_path):
                    if post_id:
                        fb_image_url = get_facebook_image_url(post_id, page["token"])
                        if fb_image_url:
                            ig_image = fb_image_url
                            ig_image_type = 'url'
                            print(f"📸 Instagram: Using Facebook-hosted image URL: {ig_image[:60]}...")
                        else:
                            print("⚠️ Could not retrieve Facebook image URL.")
                            # Optionally, we could still fall through to Pollinations
                    else:
                        print("⚠️ No Facebook post ID to retrieve image from.")
                        
                # 3. Fallback to Pollinations URL
                elif image_prompt:
                    pollinations_url = f"https://image.pollinations.ai/prompt/{image_prompt}"
                    ig_image = pollinations_url
                    ig_image_type = 'url'
                    print(f"📸 Instagram: Using Pollinations public URL")
                else:
                    print("⚠️ Instagram SKIPPED: No image source available.")

                if ig_image and ig_image_type == 'url':
                    ig_post_id = post_to_instagram(
                        ig_user_id=instagram_id,
                        access_token=page["token"],
                        caption=formatted_post,
                        image_url=ig_image,  # always a public URL
                    )
                    if ig_post_id:
                        print(f"📸 Instagram posted successfully! ID: {ig_post_id}")
                    else:
                        print("❌ Instagram returned no ID.")
            except Exception as e:
                print(f"⚠️ Instagram error: {e}")

        # ---- Now clean up the temporary image file (after both Twitter and Instagram) ----
        if temp_image_path and os.path.exists(temp_image_path):
            os.remove(temp_image_path)