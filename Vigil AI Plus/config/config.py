"""
config.py - Central configuration loader for Vigil AI.

Loads static settings from .env (paths, intervals, page IDs).
Dynamic data (API keys, page tokens) are fetched from config.json.
"""

import os
import json
from dotenv import load_dotenv

# ----------------------------------------------------------------------
# 1. Load environment variables (paths, IDs, intervals)
# ----------------------------------------------------------------------
dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path)


def _get_env_var(var_name: str, default: str = None) -> str:
    """
    Safely get an environment variable.
    If it doesn't exist, return the default value – no crash.
    """
    return os.getenv(var_name, default)


# Page IDs (from .env – will be empty if .env is missing)
FB_PAGE_ID_URDU = _get_env_var("FB_PAGE_ID_URDU", default="")
FB_PAGE_ID_DEALS = _get_env_var("FB_PAGE_ID_DEALS", default="")

# Graph API version
FB_GRAPH_API_VERSION = "v26.0"

# File paths (Windows friendly)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FONT_PATH = os.path.join(PROJECT_ROOT, "assets", "fonts", "Jameel_Noori_Nastaliq.ttf")
BACKGROUND_IMAGES = [
    os.path.join(PROJECT_ROOT, "assets", "templates", "background_1.jpg"),
    os.path.join(PROJECT_ROOT, "assets", "templates", "background_2.jpg"),
]
BACKGROUND_IMAGES = [img for img in BACKGROUND_IMAGES if os.path.exists(img)]
DATABASE_PATH = os.path.join(PROJECT_ROOT, "data", "posts_history.db")
LOG_FILE_PATH = os.path.join(PROJECT_ROOT, "logs", "vigil.log")

# Scheduler intervals (defaults: 6 hours for poetry, 2 hours for deals)
POETRY_INTERVAL_HOURS = int(_get_env_var("POETRY_INTERVAL_HOURS", "6"))
DEALS_INTERVAL_HOURS = int(_get_env_var("DEALS_INTERVAL_HOURS", "2"))

# Flask & webhook
FLASK_HOST = "127.0.0.1"
FLASK_PORT = 5000
FB_VERIFY_TOKEN = _get_env_var("FB_VERIFY_TOKEN", default="my_secure_token")

# Logging
LOG_LEVEL = "INFO"

# ----------------------------------------------------------------------
# 2. Functions to fetch dynamic data from config.json
# ----------------------------------------------------------------------
CONFIG_FILE = os.path.join(PROJECT_ROOT, "config.json")


def _load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}


def get_api_key(provider: str) -> str:
    """Return the API key for a given provider (gemini, groq, etc.) from config.json."""
    config = _load_config()
    return config.get("api_keys", {}).get(provider, {}).get("key", "")


def get_model_name(provider: str) -> str:
    """Return the model name for a given provider (gemini, groq, etc.) from config.json."""
    config = _load_config()
    return config.get("api_keys", {}).get(provider, {}).get("model", "")


def get_page_token(page_id: str) -> str:
    """Return the access token for a specific page ID from config.json."""
    config = _load_config()
    for p in config.get("pages", []):
        if p["id"] == page_id:
            return p.get("token", "")
    return ""


if __name__ == "__main__":
    print("Vigil AI Configuration loaded successfully.")