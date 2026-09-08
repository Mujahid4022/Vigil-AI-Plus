import os
import shutil
import json
import time
import threading
import requests
import uuid
import pytz
from flask import Flask, request, render_template_string, redirect, url_for
from functools import wraps
from flask import Response
from datetime import datetime, timedelta
from src.engines.engine_engagement import run_engagement

# Import config functions
from config.config import get_api_key, get_model_name, get_page_token

# --- IMPORT THE TWO UNIVERSAL ENGINES ---
from src.engines.engine_1_urdu_poetry import run_engine_1  # Engine 1
from src.engines.engine_2_deals import run_engine_2  # Engine 2

# --- Configuration ---
CONFIG_FILE = "config.json"

DRIVER_FILE = "src/utils/provider_drivers.json"

def load_drivers():
    """Load the provider driver templates from JSON file."""
    if os.path.exists(DRIVER_FILE):
        with open(DRIVER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def fetch_video_from_product_page(product_url):
    """Simple requests-based video detection – works only if video URL is in static HTML."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(product_url, headers=headers, timeout=10)
        html = resp.text
        import re, json
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
    except:
        return None

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


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    # If file doesn't exist, create it with default empty structure
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


# --- Flask App ---
app = Flask(__name__)

# ========== GLOBAL BOT STATE ==========
BOT_PAUSED = False

# ========== AUTHENTICATION ==========
USERNAME = "admin"
PASSWORD = "vigilai4042"  # CHANGE THIS!


def check_auth(username, password):
    return username == USERNAME and password == PASSWORD


def authenticate():
    return Response(
        "Login required",
        401,
        {"WWW-Authenticate": 'Basic realm="Vigil AI Control Panel"'},
    )


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)

    return decorated


# ========== HTML TEMPLATE ==========
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Vigil AI Control Panel</title>
    <style>
        body { font-family: Arial; max-width: 800px; margin: 40px auto; padding: 20px; background: #f4f7f6; }
        .card { background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 20px; }
        h2, h3 { margin-top: 0; }
        input, textarea, select { width: 100%; padding: 8px; margin: 5px 0 15px 0; border: 1px solid #ccc; border-radius: 5px; box-sizing: border-box; }
        textarea { height: 80px; resize: vertical; }
        button { padding: 8px 16px; background: #007bff; color: white; border: none; border-radius: 5px; cursor: pointer; }
        button:hover { background: #0056b3; }
        .btn-danger { background: #dc3545; }
        .btn-success { background: #28a745; }
        .btn-warning { background: #ffc107; color: black; }
        .url-row { display: flex; gap: 10px; margin-bottom: 5px; }
        .url-input { flex: 1; }
        .url-list li { background: #eee; padding: 5px 10px; margin-bottom: 5px; display: flex; justify-content: space-between; }
        .edit-form { background: #f8f9fa; padding: 15px; border: 1px solid #ddd; border-radius: 5px; margin-top: 10px; display: none; }
        .provider-list { margin-top: 10px; }
        .provider-item { background: #e9ecef; padding: 8px 12px; margin: 5px 0; border-radius: 5px; display: flex; justify-content: space-between; align-items: center; }
        .provider-item span { font-weight: bold; }
                /* ===== COLLAPSIBLE ACCORDION ===== */
        .collapsible-header {
            background: #007bff;
            color: white;
            cursor: pointer;
            padding: 12px 18px;
            border-radius: 8px;
            margin-top: 15px;
            margin-bottom: 0px;
            font-weight: bold;
            display: flex;
            justify-content: space-between;
            align-items: center;
            user-select: none;
            transition: background 0.2s;
        }
        .collapsible-header:hover {
            background: #0056b3;
        }
        .collapsible-header .arrow {
            transition: transform 0.3s;
            font-size: 18px;
        }
        .collapsible-header.active .arrow {
            transform: rotate(180deg);
        }
        .collapsible-content {
            background: white;
            padding: 20px;
            border-radius: 0 0 10px 10px;
            margin-bottom: 15px;
            display: none;
            border-left: 3px solid #007bff;
            border-right: 1px solid #ddd;
            border-bottom: 1px solid #ddd;
        }
        .collapsible-content.active {
            display: block;
        }
        
        /* ===== SUB-TABS ===== */
        .sub-tab-bar {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            border-bottom: 2px solid #eee;
            padding-bottom: 10px;
            flex-wrap: wrap;
        }
        .sub-tab-btn {
            padding: 8px 18px;
            background: #f4f7f6;
            border: 1px solid #ddd;
            border-radius: 20px;
            cursor: pointer;
            font-weight: bold;
            font-size: 14px;
            color: #000000;
            transition: all 0.2s;
        }
        .sub-tab-btn:hover {
            background: #e9ecef;
        }
        .sub-tab-btn.active {
            background: #007bff;
            color: white;
            border-color: #007bff;
        }
        .sub-tab-content {
            display: none;
        }
        .sub-tab-content.active {
            display: block;
        }
                /* ===== LOCKED TOGGLE ===== */
        .toggle-wrapper {
            display: flex;
            align-items: center;
            gap: 15px;
            margin: 10px 0 15px 0;
            padding: 10px 15px;
            background: #f8f9fa;
            border-radius: 8px;
            border: 1px solid #e9ecef;
        }
        .toggle-wrapper label {
            margin: 0;
            font-weight: bold;
            cursor: pointer;
        }
        .toggle-switch {
            position: relative;
            width: 50px;
            height: 26px;
            flex-shrink: 0;
        }
        .toggle-switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }
        .toggle-slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: #ccc;
            transition: 0.3s;
            border-radius: 34px;
        }
        .toggle-slider:before {
            position: absolute;
            content: "";
            height: 18px;
            width: 18px;
            left: 4px;
            bottom: 4px;
            background: white;
            transition: 0.3s;
            border-radius: 50%;
        }
        .toggle-switch input:checked + .toggle-slider {
            background: #28a745;
        }
        .toggle-switch input:checked + .toggle-slider:before {
            transform: translateX(24px);
        }
        .toggle-switch input:disabled + .toggle-slider {
            background: #e9ecef;
            opacity: 0.6;
            cursor: not-allowed;
        }
        .toggle-switch input:disabled + .toggle-slider:before {
            background: #adb5bd;
        }
        .toggle-status {
            font-size: 14px;
            color: #6c757d;
        }
        .toggle-status.active {
            color: #28a745;
            font-weight: bold;
        }
        .toggle-status.inactive {
            color: #dc3545;
        }
        .toggle-warning {
            font-size: 13px;
            color: #dc3545;
            background: #f8d7da;
            padding: 4px 10px;
            border-radius: 4px;
            border: 1px solid #f5c6cb;
            display: none;
        }
        .toggle-warning.show {
            display: inline-block;
        }
         .btn-remove {
            background: #dc3545;
            color: white;
            border: none;
            border-radius: 5px;
            padding: 4px 10px;
            cursor: pointer;
            font-size: 12px;
        }
        .btn-remove:hover {
            background: #c82333;
        }
        .hidden-product {
            display: none !important;
        }
        .badge-video {
            background: #22c55e;
            color: white;
            padding: 2px 12px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: bold;
            display: inline-block;
            margin: 5px 0;
        }
        .badge-image {
            background: #9ca3af;
            color: white;
            padding: 2px 12px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: bold;
            display: inline-block;
            margin: 5px 0;
        }
    </style>
<script>
// ===== Toggle URLs (Existing) =====
function toggleUrls(pageId) {
    var list = document.getElementById('urlList-' + pageId);
    var btn = document.getElementById('urlToggleBtn-' + pageId);
    if (list.style.display === 'none') {
        list.style.display = 'block';
        btn.textContent = 'Hide';
    } else {
        list.style.display = 'none';
        btn.textContent = 'Show';
    }
}

// ===== ACCORDION: Click header to expand/collapse =====
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.collapsible-header').forEach(header => {
        header.addEventListener('click', function() {
            this.classList.toggle('active');
            const content = this.nextElementSibling;
            if (content.style.display === 'block') {
                content.style.display = 'none';
            } else {
                content.style.display = 'block';
            }
        });
    });

    // ===== SUB-TABS: Switch between Twitter, Telegram, Pinterest, Webhooks =====
    document.querySelectorAll('.sub-tab-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const parentContainer = this.closest('.collapsible-content');
            parentContainer.querySelectorAll('.sub-tab-btn').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            
            parentContainer.querySelectorAll('.sub-tab-content').forEach(div => div.classList.remove('active'));
            const targetId = this.getAttribute('data-target');
            document.getElementById(targetId).classList.add('active');
        });
    });

    // ===== AUTO-CLICK first sub-tab to show default view =====
    document.querySelectorAll('.sub-tab-bar').forEach(bar => {
        const firstBtn = bar.querySelector('.sub-tab-btn');
        if (firstBtn) firstBtn.click();
    });
});

    // ===== TWITTER TOGGLE: Lock if global keys missing =====
    function setupTwitterToggle(toggleId, warningId, statusId) {
        const toggle = document.getElementById(toggleId);
        const warning = document.getElementById(warningId);
        const status = document.getElementById(statusId);
        
        if (!toggle) return;
        
        toggle.addEventListener('change', function() {
            if (this.checked && this.disabled) {
                // This should never happen, but just in case
                this.checked = false;
                if (warning) warning.classList.add('show');
                return;
            }
            if (this.checked) {
                if (warning) warning.classList.remove('show');
                if (status) {
                    status.textContent = '✅ Enabled for this page';
                    status.className = 'toggle-status active';
                }
            } else {
                if (status) {
                    status.textContent = '❌ Disabled for this page';
                    status.className = 'toggle-status inactive';
                }
            }
        });
    }

    // Wait for DOM to load
    document.addEventListener('DOMContentLoaded', function() {
        // Setup Add Page toggle
        setupTwitterToggle('twitter_enabled', 'twitter_warning', 'twitter_status');
        // Setup Edit Page toggle
        setupTwitterToggle('edit_twitter_enabled', 'edit_twitter_warning', 'edit_twitter_status');
    });

</script>
</head>
<body>
    <div class="card">
        <h2>🚀 Vigil AI Bot Control Panel</h2>
        <p>
            Manage your API keys and connected Facebook pages.
            <span style="float:right;">
                <a href="/analytics" target="_blank">📊 View Analytics</a>
            </span>
        </p>
        <div style="display:flex; align-items:center; flex-wrap:wrap; gap:15px; margin-top:10px;">
            <form method="POST" action="/toggle_pause" style="display:inline;">
                <button type="submit" class="btn-warning">
                    {% if bot_paused %}
                        ▶️ Resume Bot
                    {% else %}
                        ⏸️ Pause Bot
                    {% endif %}
                </button>
            </form>
            <span style="font-weight:bold;">
                Status: {% if bot_paused %} 🔴 PAUSED {% else %} 🟢 RUNNING {% endif %}
            </span>
            <a href="/affiliate" style="text-decoration:none; margin-left:auto;">
                <button class="btn-success" style="padding:6px 14px; font-size:14px;">
                    🔗 Go to Affiliate Marketing Dashboard
                </button>
            </a>
        </div>
    </div>

<!-- 1. API Key Management (Collapsible) -->
<div class="collapsible-header">
    🔑 Manage Your AI API Keys <span class="arrow">▼</span>
</div>
<div class="collapsible-content">
    <p>Save a key for a provider. Once saved, it will appear in the "Add Page" dropdown below.</p>
    <form method="POST" action="/add_api_key">
        <label>AI Provider</label>
        <select name="ai_provider" required>
            <option value="gemini">Google Gemini</option>
            <option value="groq">Groq Cloud</option>
            <option value="openai">OpenAI (ChatGPT)</option>
            <option value="anthropic">Anthropic (Claude)</option>
            <option value="mistral">Mistral AI</option>
            <option value="deepseek">DeepSeek</option>
        </select>
        <label>API Key</label>
        <input type="text" name="api_key" required placeholder="Enter your API key for the selected provider...">
        <label>Model Name (Optional - leave blank for default)</label>
        <input type="text" name="model_name" placeholder="e.g. openai/gpt-oss-120b or claude-sonnet-5">
        <button type="submit" class="btn-success" style="width:100%;">💾 Save API Key</button>
    </form>

    <!-- ===== NEW: Agnes AI Key (Image Generation) ===== -->
    <hr style="margin: 20px 0;">
    <form method="POST" action="/add_agnes_key">
        <label>🖼️ Agnes AI API Key (for image generation)</label>
        <input type="text" name="agnes_api_key" value="{{ agnes_api_key or '' }}" 
               placeholder="Enter your Agnes AI API key..." 
               style="width:100%; padding:8px; margin:5px 0 15px 0; border:1px solid #ccc; border-radius:5px; box-sizing:border-box;">
        <button type="submit" class="btn-success" style="width:100%;">💾 Save Agnes Key</button>
    </form>

    <div class="provider-list">
        <strong>Saved API Keys:</strong>
        {% for provider, data in api_keys.items() %}
        <div class="provider-item">
            <span>{{ provider.capitalize() }} (Model: {{ data.model or 'default' }})</span>
            <div>
                <form method="POST" action="/delete_api_key/{{ provider }}" style="display:inline;">
                    <button type="submit" class="btn-danger" style="padding: 2px 8px; font-size: 12px;">Remove</button>
                </form>
            </div>
        </div>
        {% endfor %}
    </div>
</div>

<!-- 2. Add New Page (Collapsible) -->
<div class="collapsible-header">
    ➕ Add New Facebook Page <span class="arrow">▼</span>
</div>
<div class="collapsible-content">
    <form method="POST" action="/add_page">
        <label>Facebook Page ID</label>
        <input type="text" name="page_id" required placeholder="e.g. 123456789">
        <label>Facebook Page Name (Optional - for easy identification)</label>
        <input type="text" name="page_name" placeholder="e.g., My Deals Page">
        <label>Facebook Access Token</label>
        <input type="text" name="page_token" required placeholder="EAAaF...">
        <label>AI Provider (Must have key saved above)</label>
        <select name="ai_provider" required>
            {% if not api_keys %}
                <option disabled>⚠️ Please save an API key first</option>
            {% else %}
                {% for provider in api_keys.keys() %}
                    <option value="{{ provider }}">{{ provider.capitalize() }}</option>
                {% endfor %}
            {% endif %}
        </select>
        <label>Post Language</label>
        <select name="post_language" required>
            <option value="Urdu">Urdu</option>
            <option value="English">English</option>
            <option value="Both">Both (Urdu & English)</option>
            <option value="Auto">Auto-Detect (Based on Brief)</option>
        </select>
        <label>Page Brief / Topic</label>
        <textarea name="brief" required placeholder="e.g. 'I run a small bookstore in Lahore. I want to post daily book recommendations.'"></textarea>
        <label>Provider Priority (comma‑separated, e.g. gemini,groq,openai)</label>
        <input type="text" name="provider_priority" value="gemini" placeholder="gemini,groq,openai">
        <label>Posts per run ...</label>
        <input type="number" name="posts_per_run" value="2" min="1" max="10">
        <label>Post interval ...</label>
        <input type="number" name="post_interval" value="30" min="5" max="300">
        <label>Instagram Account ID (Optional)</label>
        <input type="text" name="instagram_id" placeholder="e.g. 17841412345678901" value="">
        
            <!-- ===== Twitter Toggle ===== -->
            <div class="toggle-wrapper">
                <div class="toggle-switch">
                    <input type="checkbox" id="twitter_enabled" name="twitter_enabled" value="true" 
                           {% if not twitter_configured %}disabled{% endif %}>
                    <span class="toggle-slider"></span>
                </div>
                <label for="twitter_enabled">🐦 Enable Twitter Cross-Posting</label>
                <span id="twitter_status" class="toggle-status {% if twitter_configured %}active{% else %}inactive{% endif %}">
                    {% if twitter_configured %}✅ Global keys configured{% else %}❌ No global keys found{% endif %}
                </span>
                <span id="twitter_warning" class="toggle-warning {% if not twitter_configured %}show{% endif %}">
                    ⚠️ Please add Twitter API keys in the Integrations card first.
                </span>
            </div>        
        <label>Lead Webhook URL (Optional - for this page)</label>
        <input type="text" name="lead_webhook" placeholder="https://your-zapier-webhook.com">
        
        <label>Schedule (Post every X hours)</label>
        <input type="number" name="interval_hours" value="2" min="1" max="24" required>
        <button type="submit" class="btn-success" style="width:100%; margin-top:15px;">💾 Save Page & Start Bot</button>
    </form>
</div>

<!-- 2.5. Integrations (Collapsible + Sub-Tabs) -->
<div class="collapsible-header">
    🔗 Integrations (Twitter, Telegram, Pinterest, Webhooks) <span class="arrow">▼</span>
</div>
<div class="collapsible-content">
    <p>Paste your API keys for cross-posting, alerts, and tracking.</p>
    
    <!-- Sub-Tab Navigation -->
    <div class="sub-tab-bar">
        <button class="sub-tab-btn active" data-target="tab-twitter">🐦 Twitter</button>
        <button class="sub-tab-btn" data-target="tab-telegram">📱 Telegram</button>
        <button class="sub-tab-btn" data-target="tab-pinterest">📌 Pinterest</button>
        <button class="sub-tab-btn" data-target="tab-webhooks">🌐 Webhooks</button>
    </div>
    
    <form method="POST" action="/update_integrations">
        
        <!-- TAB 1: Twitter -->
        <div id="tab-twitter" class="sub-tab-content active">
            <h4>🐦 Twitter</h4>
            <label>Consumer Key</label>
            <input type="text" name="twitter_consumer_key" value="{{ twitter.consumer_key or '' }}">
            <label>Consumer Secret</label>
            <input type="text" name="twitter_consumer_secret" value="{{ twitter.consumer_secret or '' }}">
            <label>Access Token</label>
            <input type="text" name="twitter_access_token" value="{{ twitter.access_token or '' }}">
            <label>Access Token Secret</label>
            <input type="text" name="twitter_access_token_secret" value="{{ twitter.access_token_secret or '' }}">
        </div>
        
        <!-- TAB 2: Telegram -->
        <div id="tab-telegram" class="sub-tab-content">
            <h4>📱 Telegram</h4>
            <label>Bot Token (from @BotFather)</label>
            <input type="text" name="telegram_token" value="{{ telegram_token or '' }}">
            <label>Authorized Telegram User IDs (comma separated)</label>
            <input type="text" name="authorized_users" value="{{ authorized_users or '' }}" placeholder="e.g. 123456789, 987654321">
        </div>
        
        <!-- TAB 3: Pinterest (NEW) -->
        <div id="tab-pinterest" class="sub-tab-content">
            <h4>📌 Pinterest (Business API)</h4>
            <p style="font-size:14px; color:#555;">Get your credentials from <a href="https://developers.pinterest.com" target="_blank">developers.pinterest.com</a></p>
            <label>App ID (Client ID)</label>
            <input type="text" name="pinterest_client_id" value="{{ pinterest.client_id or '' }}" placeholder="e.g. 1234567890">
            <label>App Secret (Client Secret)</label>
            <input type="text" name="pinterest_client_secret" value="{{ pinterest.client_secret or '' }}" placeholder="e.g. abcdef123456">
            <label>Access Token</label>
            <input type="text" name="pinterest_access_token" value="{{ pinterest.access_token or '' }}" placeholder="pina_...">
            <label>Default Board ID (Optional)</label>
            <input type="text" name="pinterest_default_board" value="{{ pinterest.default_board or '' }}" placeholder="e.g. 1234567890">
            <p style="font-size:12px; color:#888; margin-top:5px;">Leave Board ID blank if you want to set it per-page.</p>
        </div>
        
        <!-- TAB 4: Webhooks -->
        <div id="tab-webhooks" class="sub-tab-content">
            <h4>🌐 Lead Webhook</h4>
            <label>Webhook URL (Zapier/Mailchimp)</label>
            <input type="text" name="lead_webhook" value="{{ lead_webhook or '' }}" placeholder="https://your-zapier-webhook.com">
        </div>
        
        <!-- ONE SAVE BUTTON FOR ALL -->
        <button type="submit" class="btn-success" style="width:100%; margin-top:15px;">💾 Save Integrations</button>
    </form>
</div>

    <!-- 3. Active Pages List -->
    <div class="card">
        <h3>📋 Your Active Pages ({{ pages|length }})</h3>
        {% if pages %}
            {% for page in pages %}
            <div class="page-item">
                <div>
                    <strong>Page Name:</strong> {{ page.get('name', page.id) }} | 
                    <strong>Page ID:</strong> {{ page.id }} | 
                    <strong>Interval:</strong> {{ page.interval }} hours
                </div>
                <div class="meta"><strong>Provider:</strong> {{ page.get('ai_provider', 'gemini').capitalize() }} | <strong>Lang:</strong> {{ page.get('language', 'Urdu') }}</div>
                <div><strong>Brief:</strong> {{ page.brief[:50] }}...</div>
                <div style="margin: 10px 0;">
                    <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                        <strong>URLs:</strong>
                        <button onclick="toggleUrls('{{ page.id }}')" id="urlToggleBtn-{{ page.id }}" class="btn-warning" style="padding:2px 10px; font-size:12px;">Show</button>
                    </div>
                    <div id="urlList-{{ page.id }}" style="display:none;">
                        <ul class="url-list">
                            {% for url in page.urls %}
                            <li><span>{{ url }}</span>
                                <form method="POST" action="/remove_url/{{ page.id }}" style="display:inline;">
                                    <input type="hidden" name="url_to_remove" value="{{ url }}">
                                    <button class="btn-danger" style="padding:2px 8px;">X</button>
                                </form>
                            </li>
                            {% endfor %}
                            <li style="background:none; padding:0;">
                                <form method="POST" action="/add_url/{{ page.id }}" style="display:flex; gap:5px;">
                                    <input type="text" name="new_url" placeholder="Add URL" style="flex:1; padding:5px;">
                                    <button style="padding:5px 10px;">+</button>
                                </form>
                            </li>
                        </ul>
                    </div>
                    {% if page.google_query %}
                    <div style="margin-top:5px; font-size:12px; color:#555;">
                        <strong>Google Query:</strong> {{ page.google_query }}
                    </div>
                    {% endif %}
                    <div style="font-size:12px; color:#555; margin-top:5px;">
                        <strong>Posts per run:</strong> {{ page.posts_per_run or 2 }} | 
                        <strong>Post interval:</strong> {{ page.post_interval or 30 }}s
                    </div>
                </div>
                <div style="display:flex; gap:10px; margin-top:10px;">
                    <button class="btn-warning" onclick="document.getElementById('edit-form-{{ page.id }}').style.display='block'">✏️ Edit</button>
                    <form method="POST" action="/test_post/{{ page.id }}" style="display:inline;"><button class="btn-success">🟢 Test</button></form>
                    <form method="POST" action="/delete_page/{{ page.id }}" style="display:inline;"><button class="btn-danger">🗑️ Remove</button></form>
                </div>
                <div id="edit-form-{{ page.id }}" class="edit-form">
                    <h4>Edit Page: {{ page.id }}</h4>
                    <form method="POST" action="/edit_page/{{ page.id }}">
                        <label>Access Token</label><input type="text" name="edit_token" value="{{ page.token }}">
                        <label>Page Name</label>
                        <input type="text" name="edit_page_name" value="{{ page.get('name', '') }}" placeholder="e.g., My Deals Page">
                        <label>AI Provider</label>
                        <select name="edit_ai_provider">
                            {% for provider in api_keys.keys() %}
                                <option value="{{ provider }}" {% if page.get('ai_provider') == provider %}selected{% endif %}>{{ provider.capitalize() }}</option>
                            {% endfor %}
                        </select>
                        <label>Language</label>
                        <select name="edit_language">
                            <option value="Urdu" {% if page.get('language') == 'Urdu' %}selected{% endif %}>Urdu</option>
                            <option value="English" {% if page.get('language') == 'English' %}selected{% endif %}>English</option>
                            <option value="Both" {% if page.get('language') == 'Both' %}selected{% endif %}>Both</option>
                            <option value="Auto" {% if page.get('language') == 'Auto' %}selected{% endif %}>Auto-Detect</option>
                        </select>
                        <label>Brief</label><textarea name="edit_brief">{{ page.brief }}</textarea>
                        <label>Provider Priority</label>
                        <input type="text" name="edit_provider_priority" value="{{ page.provider_priority or 'gemini' }}" placeholder="gemini,groq,openai">
                        <label>Posts per run</label>
                        <input type="number" name="edit_posts_per_run" value="{{ page.posts_per_run or 2 }}" min="1" max="10">
                        <label>Post interval (seconds)</label>
                        <input type="number" name="edit_post_interval" value="{{ page.post_interval or 30 }}" min="5" max="300">
                        <label>Instagram Account ID</label>
                        <input type="text" name="edit_instagram_id" value="{{ page.get('instagram_account_id', '') }}" placeholder="e.g. 17841412345678901">
                        
                        <!-- ===== NEW: Edit Twitter & Webhook Fields ===== -->
                        <!-- ===== Twitter Toggle (Edit) ===== -->
                        <div class="toggle-wrapper">
                            <div class="toggle-switch">
                                <input type="checkbox" id="edit_twitter_enabled" name="edit_twitter_enabled" value="true"
                                       {% if page.get('twitter_enabled', False) %}checked{% endif %}
                                       {% if not twitter_configured %}disabled{% endif %}>
                                <span class="toggle-slider"></span>
                            </div>
                            <label for="edit_twitter_enabled">🐦 Enable Twitter Cross-Posting</label>
                            <span id="edit_twitter_status" class="toggle-status {% if twitter_configured %}active{% else %}inactive{% endif %}">
                                {% if twitter_configured %}✅ Global keys configured{% else %}❌ No global keys found{% endif %}
                            </span>
                            <span id="edit_twitter_warning" class="toggle-warning {% if not twitter_configured %}show{% endif %}">
                                ⚠️ Please add Twitter API keys in the Integrations card first.
                            </span>
                        </div>

                        <label>Lead Webhook URL (for this page)</label>
                        <input type="text" name="edit_lead_webhook" value="{{ page.get('lead_webhook_url', '') }}" placeholder="https://your-zapier-webhook.com">
                        <!-- ============================================ -->
                        
                        <label>Interval</label>
                        <input type="number" name="edit_interval" value="{{ page.interval }}" min="1">
                        <div style="margin-top:15px; display:flex; gap:10px;">
                            <button type="submit" class="btn-success">💾 Save Changes</button>
                            <button type="button" class="btn-danger" onclick="document.getElementById('edit-form-{{ page.id }}').style.display='none'">Cancel</button>
                        </div>
                    </form>
                </div>
            </div>
            {% endfor %}
        {% else %}
            <p style="color:#888; text-align:center;">No pages added yet. Add your first page above!</p>
        {% endif %}
    </div>
</body>
</html>
"""

# ===================== ROUTES =====================


@app.route("/")
@requires_auth
def index():
    config = load_config()
    twitter_creds = config.get("twitter_credentials", {})
    twitter_configured = bool(
        twitter_creds.get("consumer_key") and
        twitter_creds.get("consumer_secret") and
        twitter_creds.get("access_token") and
        twitter_creds.get("access_token_secret")
    )
    agnes_api_key = config.get("agnes_api", {}).get("key", "")
    return render_template_string(
        HTML_TEMPLATE,
        api_keys=config.get("api_keys", {}),
        pages=config.get("pages", []),
        bot_paused=BOT_PAUSED,
        twitter=twitter_creds,
        twitter_configured=twitter_configured,  # <-- NEW
        telegram_token=config.get("telegram_bot_token", ""),
        lead_webhook=config.get("lead_webhook_url", ""),
        authorized_users=",".join([str(uid) for uid in config.get("authorized_telegram_users", [])]),
        pinterest=config.get("pinterest_credentials", {}),
        agnes_api_key=agnes_api_key,
    )


@app.route("/add_api_key", methods=["POST"])
@requires_auth
def add_api_key():
    config = load_config()
    provider = request.form.get("ai_provider")
    key = request.form.get("api_key").strip()
    model = request.form.get("model_name").strip()
    if "api_keys" not in config:
        config["api_keys"] = {}
    config["api_keys"][provider] = {"key": key, "model": model}
    save_config(config)
    return redirect(url_for("index"))


@app.route("/add_google_keys", methods=["POST"])
@requires_auth
def add_google_keys():
    config = load_config()
    google_api = request.form.get("google_api", "").strip()
    google_engine_id = request.form.get("google_engine_id", "").strip()
    if "api_keys" not in config:
        config["api_keys"] = {}
    config["api_keys"]["google_api"] = google_api
    config["api_keys"]["google_engine_id"] = google_engine_id
    save_config(config)
    return redirect(url_for("index"))


@app.route("/delete_api_key/<provider>", methods=["POST"])
@requires_auth
def delete_api_key(provider):
    config = load_config()
    if provider in config.get("api_keys", {}):
        del config["api_keys"][provider]
        save_config(config)
    return redirect(url_for("index"))

@app.route("/add_agnes_key", methods=["POST"])
@requires_auth
def add_agnes_key():
    config = load_config()
    agnes_key = request.form.get("agnes_api_key", "").strip()
    if "agnes_api" not in config:
        config["agnes_api"] = {}
    config["agnes_api"]["key"] = agnes_key
    save_config(config)
    print(f"✅ Agnes AI key saved.")
    return redirect(url_for("index"))


@app.route("/add_page", methods=["POST"])
@requires_auth
def add_page():
    config = load_config()
    if request.form.get("add_url_action"):
        return redirect(url_for("index"))

    page_id = request.form.get("page_id")
    if not any(p["id"] == page_id for p in config["pages"]):
        token = request.form.get("page_token")
        config["pages"].append(
            {
                "id": page_id,
                "name": request.form.get("page_name", ""),
                "token": token,
                "ai_provider": request.form.get("ai_provider", "gemini"),
                "language": request.form.get("post_language", "Urdu"),
                "brief": request.form.get("brief", ""),
                "urls": [],
                "interval": int(request.form.get("interval_hours", 2)),
                "last_posted": 0,
                "provider_priority": request.form.get("provider_priority", "gemini"),
                "posts_per_run": int(request.form.get("posts_per_run", 2)),
                "post_interval": int(request.form.get("post_interval", 30)),
                "instagram_account_id": request.form.get("instagram_id", ""),
                # ----- NEW PER‑PAGE FIELDS -----
                "twitter_enabled": request.form.get("twitter_enabled") == "true",
                "lead_webhook_url": request.form.get("lead_webhook", ""),
            }
        )
        save_config(config)
        update_env_token(page_id, token)
    return redirect(url_for("index"))


@app.route("/edit_page/<page_id>", methods=["POST"])
@requires_auth
def edit_page(page_id):
    config = load_config()
    new_token = None

    # --- DEBUG: See what value was submitted ---
    interval_received = request.form.get("edit_interval")
    print(f"🔍 Received edit_interval: {interval_received}")

    for p in config["pages"]:
        if p["id"] == page_id:
            new_token = request.form.get("edit_token")
            p["token"] = new_token
            # Auto-fetch the real Facebook Page Name
            real_name = get_facebook_page_name(p["id"], p["token"])
            if real_name:
                p["name"] = real_name
            else:
                p["name"] = request.form.get("edit_page_name", "")
            p["ai_provider"] = request.form.get("edit_ai_provider", "gemini")
            p["language"] = request.form.get("edit_language", "Urdu")
            p["brief"] = request.form.get("edit_brief")
            p["interval"] = int(request.form.get("edit_interval", 2))

            # --- DEBUG: Confirm the value was set ---
            print(f"✅ Set interval to {p['interval']} for page {page_id}")

            p["provider_priority"] = request.form.get(
                "edit_provider_priority", "gemini"
            )
            p["posts_per_run"] = int(request.form.get("edit_posts_per_run", 2))
            p["post_interval"] = int(request.form.get("edit_post_interval", 30))
            p["instagram_account_id"] = request.form.get("edit_instagram_id", "")
            # ----- NEW PER‑PAGE FIELDS -----
            p["twitter_enabled"] = request.form.get("edit_twitter_enabled") == "true"
            p["lead_webhook_url"] = request.form.get("edit_lead_webhook", "")
            break

    if new_token is not None:
        update_env_token(page_id, new_token)

    # --- IMPORTANT: Always save config, even if token didn't change ---
    save_config(config)
    print("💾 Config saved.")

    return redirect(url_for("index"))


@app.route("/add_url/<page_id>", methods=["POST"])
@requires_auth
def add_url(page_id):
    config = load_config()
    new_url = request.form.get("new_url", "").strip()
    for p in config["pages"]:
        if p["id"] == page_id and new_url and new_url not in p["urls"]:
            p["urls"].append(new_url)
            break
    save_config(config)
    return redirect(url_for("index"))


@app.route("/remove_url/<page_id>", methods=["POST"])
@requires_auth
def remove_url(page_id):
    config = load_config()
    url_to_remove = request.form.get("url_to_remove")
    for p in config["pages"]:
        if p["id"] == page_id and url_to_remove in p["urls"]:
            p["urls"].remove(url_to_remove)
            break
    save_config(config)
    return redirect(url_for("index"))


@app.route("/delete_page/<page_id>", methods=["POST"])
@requires_auth
def delete_page(page_id):
    config = load_config()
    config["pages"] = [p for p in config["pages"] if p["id"] != page_id]
    save_config(config)
    return redirect(url_for("index"))


@app.route("/update_integrations", methods=["POST"])
@requires_auth
def update_integrations():
    """Saves Twitter, Telegram, Webhook, and Pinterest keys."""
    config = load_config()
    
    # Twitter
    config["twitter_credentials"] = {
        "consumer_key": request.form.get("twitter_consumer_key", ""),
        "consumer_secret": request.form.get("twitter_consumer_secret", ""),
        "access_token": request.form.get("twitter_access_token", ""),
        "access_token_secret": request.form.get("twitter_access_token_secret", ""),
    }
    
    # Telegram Token
    config["telegram_bot_token"] = request.form.get("telegram_token", "")
    
    # Authorized Telegram Users
    auth_users = request.form.get("authorized_users", "").strip()
    if auth_users:
        config["authorized_telegram_users"] = [int(x.strip()) for x in auth_users.split(",") if x.strip()]
    else:
        config["authorized_telegram_users"] = []
    
    # Lead Webhook
    config["lead_webhook_url"] = request.form.get("lead_webhook", "")
    
    # Pinterest (NEW)
    config["pinterest_credentials"] = {
        "client_id": request.form.get("pinterest_client_id", ""),
        "client_secret": request.form.get("pinterest_client_secret", ""),
        "access_token": request.form.get("pinterest_access_token", ""),
        "default_board": request.form.get("pinterest_default_board", ""),
    }
       
    save_config(config)
    print("✅ Integrations updated successfully.")
    return redirect(url_for("index"))


# ===================== ANALYTICS DASHBOARD =====================

@app.route("/analytics")
@requires_auth
def analytics():
    """Displays performance analytics from the CSV log."""
    import csv
    import os
    from collections import defaultdict

    log_file = "performance_log.csv"
    if not os.path.exists(log_file):
        return "<h3>No analytics data yet. Run the bot and generate some posts first.</h3>"

    data = []
    with open(log_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)

    if not data:
        return "<h3>No data rows found.</h3>"

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
    <h2>📊 Vigil AI Performance Dashboard</h2>
    <p><strong>Total Posts Analyzed:</strong> {total_posts}</p>
    <p><strong>Avg Impressions per Post:</strong> {avg_impressions:.1f}</p>
    <p><strong>Avg Likes per Post:</strong> {avg_likes:.1f}</p>
    <p><strong>Avg Comments per Post:</strong> {avg_comments:.1f}</p>
    <hr>
    <h3>📋 Breakdown by Page</h3>
    <ul>
    """
    for pid, stats in page_stats.items():
        html += f"<li><strong>Page {pid}:</strong> {stats['posts']} posts, {stats['impressions']} impressions, {stats['likes']} likes</li>"

    html += """
    </ul>
    <hr>
    <h3>📝 Recent Posts (Last 10)</h3>
    <table border="1" cellpadding="5">
        <tr><th>Time</th><th>Page</th><th>Impressions</th><th>Likes</th><th>Comments</th><th>Shares</th></tr>
    """
    for row in data[-10:]:
        html += f"<tr><td>{row.get('timestamp', '')}</td><td>{row.get('page_id', '')}</td><td>{row.get('impressions', 0)}</td><td>{row.get('likes', 0)}</td><td>{row.get('comments', 0)}</td><td>{row.get('shares', 0)}</td></tr>"

    html += "</table>"
    return html

# ===================== AFFILIATE MARKETING DASHBOARD (BATCH + SCHEDULE) =====================

AFFILIATE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Vigil AI - Affiliate Marketing</title>
    <style>
        body { font-family: Arial; max-width: 1000px; margin: 40px auto; padding: 20px; background: #f4f7f6; }
        .card { background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 20px; }
        h2, h3 { margin-top: 0; }
        input, textarea, select { width: 100%; padding: 8px; margin: 5px 0 15px 0; border: 1px solid #ccc; border-radius: 5px; box-sizing: border-box; }
        button { padding: 8px 16px; background: #007bff; color: white; border: none; border-radius: 5px; cursor: pointer; }
        button:hover { background: #0056b3; }
        .btn-success { background: #28a745; }
        .btn-danger { background: #dc3545; }
        .btn-warning { background: #ffc107; color: black; }
        .product-card { border: 1px solid #ddd; padding: 15px; margin: 15px 0; border-radius: 8px; display: flex; gap: 20px; align-items: flex-start; background: #f9f9f9; }
        .product-image { width: 150px; height: 150px; object-fit: contain; background: white; border-radius: 8px; border: 1px solid #eee; }
        .product-details { flex: 1; }
        .provider-item { background: #e9ecef; padding: 10px; margin: 5px 0; border-radius: 5px; display: flex; justify-content: space-between; align-items: center; }
        .queue-item { background: #e3f2fd; padding: 10px; margin: 5px 0; border-radius: 5px; display: flex; justify-content: space-between; align-items: center; }
        .back-link { display: inline-block; margin-bottom: 20px; }
        .inline-flex { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
        textarea { height: 60px; }
    </style>
</head>
<body>
    <a href="/" class="back-link">← Back to Main Dashboard</a>
    
    <div class="card">
        <h2>🔗 Affiliate Marketing Dashboard (Batch + Schedule)</h2>
        <p>Search for products, preview them, and schedule them for your Facebook pages.</p>
    </div>

    <!-- 1. Add Provider Card -->
    <div class="card" style="background: #e3f2fd;">
        <h3>➕ Add Affiliate Provider</h3>
        <form method="POST" action="/add_provider" id="provider_form">
            
            <label>Select Provider</label>
            <select name="provider_name" id="provider_name" required onchange="updateFields()">
                <option value="">-- Select a provider --</option>
                <option value="aliexpress">AliExpress</option>
                <option value="amazon">Amazon</option>
                <option value="flipkart">Flipkart</option>
                <option value="ebay">eBay</option>
                <option value="alibaba">Alibaba</option>
                <option value="walmart">Walmart</option>
                <option value="daraz">Daraz (Pakistan)</option>
                <option value="admitad">Admitad (166+ Brands)</option>
            </select>

            <!-- Dynamic Fields Container -->
            <div id="fields_container">
                <div id="field_api_key" style="display:none;">
                    <label id="label_api_key">API Key</label>
                    <input type="text" name="api_key" id="api_key" placeholder="Enter your API Key">
                </div>

                <div id="field_api_secret" style="display:none;">
                    <label id="label_api_secret">API Secret</label>
                    <input type="text" name="api_secret" id="api_secret" placeholder="Enter your API Secret">
                </div>

                <div id="field_associate_tag" style="display:none;">
                    <label id="label_associate_tag">Associate Tag</label>
                    <input type="text" name="associate_tag" id="associate_tag" placeholder="Enter your Associate Tag">
                </div>
            </div>

            <button type="submit" class="btn-success" style="width:100%; margin-top:15px;">💾 Save Provider</button>
        </form>
        
        <h4>Saved Providers:</h4>
        {% for p in providers %}
        <div class="provider-item">
            <span><strong>{{ p.nickname }}</strong></span>
            <form method="POST" action="/delete_provider/{{ p.id }}" style="display:inline;">
                <button type="submit" class="btn-danger" style="padding: 2px 10px;">🗑️ Remove</button>
            </form>
        </div>
        {% else %}
        <p style="color:#888;">No providers added yet.</p>
        {% endfor %}
    </div>

    <script>
    // ===== DYNAMIC FIELD MAPPING =====
    const PROVIDER_FIELDS = {
        "aliexpress": {
            "fields": ["api_key", "api_secret", "associate_tag"],
            "labels": {
                "api_key": "App Key (Client ID)",
                "api_secret": "App Secret (Client Secret)",
                "associate_tag": "Tracking ID"
            }
        },
        "amazon": {
            "fields": ["api_key", "api_secret", "associate_tag"],
            "labels": {
                "api_key": "Access Key",
                "api_secret": "Secret Key",
                "associate_tag": "Partner Tag (Associate Tag)"
            }
        },
        "flipkart": {
            "fields": ["api_key", "api_secret", "associate_tag"],
            "labels": {
                "api_key": "Affiliate Tracking ID",
                "api_secret": "Affiliate API Token",
                "associate_tag": "Affiliate Tracking ID (same as API Key)"
            }
        },
        "ebay": {
            "fields": ["api_key", "api_secret", "associate_tag"],
            "labels": {
                "api_key": "App ID (Client ID)",
                "api_secret": "Cert ID (Client Secret)",
                "associate_tag": "RuName (Redirect URL Name)"
            }
        },
        "alibaba": {
            "fields": ["api_key", "api_secret"],
            "labels": {
                "api_key": "App Key (AppKey)",
                "api_secret": "App Secret (AppSecret)"
            }
        },
        "walmart": {
            "fields": ["api_key"],
            "labels": {
                "api_key": "API Key"
            }
        },
        "daraz": {
            "fields": ["api_key"],
            "labels": {
                "api_key": "Parse.bot API Key"
            }
        },
        "admitad": {
            "fields": ["api_key", "associate_tag"],
            "labels": {
                "api_key": "Admitad API Key",
                "associate_tag": "Campaign ID"
            }
        }
    };

    function updateFields() {
        const provider = document.getElementById('provider_name').value;
        const fieldMap = PROVIDER_FIELDS[provider];

        // Hide all fields first
        document.getElementById('field_api_key').style.display = 'none';
        document.getElementById('field_api_secret').style.display = 'none';
        document.getElementById('field_associate_tag').style.display = 'none';

        if (!fieldMap) return;

        // Show and label the required fields
        fieldMap.fields.forEach(field => {
            const div = document.getElementById('field_' + field);
            if (div) {
                div.style.display = 'block';
                const label = document.getElementById('label_' + field);
                if (label && fieldMap.labels[field]) {
                    label.textContent = fieldMap.labels[field];
                }
            }
        });
    }

    // ===== REMOVE PRODUCT FUNCTION (with debug) =====
    window.removeProduct = function(index) {
        console.log('🔍 removeProduct called with index:', index);
        const product = document.getElementById('product-' + index);
        console.log('🔍 Found product element:', product);
        if (product) {
            product.classList.add('hidden-product');
            console.log('✅ hidden-product class added to product-', index);
            console.log('✅ Product classes now:', product.className);
        } else {
            console.error('❌ Product element not found for index:', index);
        }
    };

    // ===== REMOVE BUTTON FALLBACK (Event Delegation) =====
    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('btn-remove')) {
            var productCard = e.target.closest('.product-card');
            if (productCard) {
                productCard.classList.add('hidden-product');
            }
        }
    });

    // ===== FILTER VIDEO PRODUCTS =====
    function filterProducts() {
        const onlyVideo = document.getElementById('filterVideoOnly').checked;
        const cards = document.querySelectorAll('.product-card');
        cards.forEach(card => {
            const hasVideo = card.dataset.hasVideo === 'true';
            if (onlyVideo && !hasVideo) {
                card.style.display = 'none';
            } else {
                card.style.display = 'flex';
            }
        });
    }

    // Run on page load to handle pre-selected provider
    document.addEventListener('DOMContentLoaded', updateFields);
</script>

    <!-- 2. Search & Schedule Card -->
    <div class="card" style="background: #fff3cd;">
        <h3>🔍 Batch Product Search & Schedule</h3>
        <form method="POST" action="/search_products">
            <label>Select Facebook Page</label>
            <select name="page_id" required>
                <option value="">-- Select a page --</option>
                {% for page in pages %}
                    <option value="{{ page.id }}">{{ page.get('name', page.id) }}</option>
                {% endfor %}
            </select>
            <label>Select Provider</label>
            <select name="provider_name" required>
                <option value="">-- Select a provider --</option>
                {% for p in providers %}
                    <option value="{{ p.nickname }}">{{ p.nickname }}</option>
                {% endfor %}
            </select>
            <label>Search Term (e.g., "wireless mouse")</label>
            <input type="text" name="search_term" required placeholder="Search for products...">
            <button type="submit" class="btn-success" style="width:100%; margin-top:15px;">🔍 Search & Preview Products</button>
        </form>

        <!-- Display Search Results -->
        {% if search_results %}
        <hr>
        <h3>📦 Product Preview ({{ search_results|length }} found)</h3>

        <div id="productContainer">
        <form method="POST" action="/schedule_affiliate_posts">
            <input type="hidden" name="page_id" value="{{ current_page_id }}">
            <input type="hidden" name="provider_name" value="{{ current_provider }}">
            <input type="hidden" name="search_term" value="{{ search_term }}">
            
            {% for product in search_results %}
            <div class="product-card" id="product-{{ loop.index0 }}" data-has-video="{{ product.has_video|lower }}">
                <img src="{{ product.image_url }}" alt="{{ product.name }}" class="product-image" onerror="this.src='https://via.placeholder.com/150'">
                <div class="product-details">
                    <strong>{{ product.name }}</strong><br>
                    <strong>Price:</strong> 
                    {% if product.sale_price_cny and product.sale_price_usd %}
                        {{ product.sale_price_cny }} {{ product.currency_cny }} (~{{ product.sale_price_usd }} {{ product.currency_usd }})
                        {% if product.original_price_cny and product.original_price_usd %}
                            <del>{{ product.original_price_cny }} {{ product.currency_cny }} (~{{ product.original_price_usd }} {{ product.currency_usd }})</del>
                        {% endif %}
                    {% else %}
                        {% if product.original_price %}
                            <del>${{ product.original_price }}</del> 
                        {% endif %}
                        <strong>${{ product.price }}</strong>
                    {% endif %}
                    <br>
                    <!-- VIDEO BADGE -->
                    {% if product.has_video %}
                        <span class="badge-video">🎬 Video Available</span>
                    {% else %}
                        <span class="badge-image">📷 Image Only</span>
                    {% endif %}
                    <br>
                    <strong>Description:</strong><br>
                    <textarea name="desc_{{ loop.index0 }}">{{ product.description or 'No description available. Please check the product link for details.' }}</textarea>
                    <div class="inline-flex">
                        <label>Schedule for:</label>
                        <input type="datetime-local" name="time_{{ loop.index0 }}" value="{{ default_time }}" required>
                        <input type="hidden" name="product_id_{{ loop.index0 }}" value="{{ product.product_id }}">
                        <input type="hidden" name="has_video_{{ loop.index0 }}" value="{{ product.has_video|lower }}">
    
                        <!-- NEW: Manual video URL input -->
                        <label style="font-size:12px; white-space:nowrap;">Video URL:</label>
                        <input type="text" name="video_url_{{ loop.index0 }}" value="{{ product.video_url or '' }}" 
                               placeholder="Paste video URL here" 
                               style="width:250px; padding:4px; font-size:12px; border:1px solid #ccc; border-radius:4px;">
    
                        <button type="submit" name="schedule_index" value="{{ loop.index0 }}" class="btn-success">📅 Schedule</button>
                        <a href="{{ product.product_url }}" target="_blank" class="btn-warning" style="padding:8px 16px; text-decoration:none; border-radius:5px;">🔗 View</a>
                        <button type="button" onclick="removeProduct('{{ loop.index0 }}')" class="btn-remove">✖ Remove</button>
                    </div>
                </div>
            </div>
            {% endfor %}
        </form>
        </div>
        {% endif %}
    </div>

    <!-- 3. Scheduled Queue -->
    <div class="card">
        <h3>📋 Scheduled Affiliate Posts ({{ scheduled_posts|length }})</h3>
        {% if scheduled_posts %}
            {% for post in scheduled_posts %}
            <div class="queue-item" style="display:flex; align-items:center; gap:15px; padding:12px; border-bottom:1px solid #eee;">
                <img src="{{ post.product_image or 'https://via.placeholder.com/50' }}" alt="{{ post.product_name }}" style="width:50px; height:50px; object-fit:contain; border-radius:5px; border:1px solid #ddd;">
                <div style="flex:1;">
                    <strong>{{ post.product_name or post.search_term }}</strong><br>
                    <span style="font-size:12px; color:#888;">Page: {{ post.page_name or post.page_id }} | Time: {{ post.scheduled_time }}</span>
                </div>
                <form method="POST" action="/cancel_scheduled/{{ post.id }}" style="display:inline;">
                    <button type="submit" class="btn-danger" style="padding: 4px 12px;">🗑️ Cancel</button>
                </form>
            </div>
            {% endfor %}
        {% else %}
            <p style="color:#888;">Queue is empty. Search and schedule products above!</p>
        {% endif %}
    </div>
</body>
</html>
"""

@app.route("/affiliate")
@requires_auth
def affiliate_dashboard():
    config = load_config()
    providers = config.get("affiliate_providers", [])
    pages = config.get("pages", [])
    # Filter out posted posts
    all_scheduled = config.get("scheduled_affiliate_posts", [])
    scheduled = [p for p in all_scheduled if not p.get("posted", False)]
    return render_template_string(
        AFFILIATE_HTML,
        providers=providers,
        pages=pages,
        scheduled_posts=scheduled,
        search_results=None,
        current_page_id="",
        current_provider="",
        default_time="",
        search_term=""
    )

@app.route("/search_products", methods=["POST"])
@requires_auth
def search_products():
    from src.utils.affiliate_api import search_products as search_products_api
    import concurrent.futures

    config = load_config()
    page_id = request.form.get("page_id")
    provider_name = request.form.get("provider_name")
    search_term = request.form.get("search_term")
    
    # Get provider credentials
    provider = None
    for p in config.get("affiliate_providers", []):
        if p["nickname"] == provider_name or p["provider_type"] == provider_name:
            provider = p
            break
    
    if not provider:
        return "Provider not found", 400
    
    # Fetch products using the universal engine
    products = search_products_api(provider, search_term)
    
    # ---- NEW: Enrich with video status ----
    def enrich_product(product):
        video_url = fetch_video_from_product_page(product.get('product_url', ''))
        product['has_video'] = bool(video_url)
        product['video_url'] = video_url
        return product

    # Use ThreadPoolExecutor to check up to 5 products at once
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        enriched_products = list(executor.map(enrich_product, products))
    
    # Filter out products that are already scheduled
    all_scheduled = config.get("scheduled_affiliate_posts", [])
    scheduled_ids = [p.get("product_id") for p in all_scheduled if p.get("product_id")]
    enriched_products = [p for p in enriched_products if p.get("product_id") not in scheduled_ids]
    
    # Re-render the page with results
    providers = config.get("affiliate_providers", [])
    pages = config.get("pages", [])
    scheduled = [p for p in all_scheduled if not p.get("posted", False)]
    
    from datetime import datetime, timedelta
    default_time = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    
    return render_template_string(
        AFFILIATE_HTML,
        providers=providers,
        pages=pages,
        scheduled_posts=scheduled,
        search_results=enriched_products,
        current_page_id=page_id,
        current_provider=provider_name,
        default_time=default_time,
        search_term=search_term
    )

@app.route("/schedule_affiliate_posts", methods=["POST"])
@requires_auth
def schedule_affiliate_posts():
    config = load_config()
    if "scheduled_affiliate_posts" not in config:
        config["scheduled_affiliate_posts"] = []
    
    page_id = request.form.get("page_id")
    provider_name = request.form.get("provider_name")
    search_term = request.form.get("search_term")
    schedule_index = request.form.get("schedule_index")
    
    if schedule_index is None or search_term is None:
        return "Missing product data", 400
    
    index = int(schedule_index)
    
    # Get description and time using the index
    desc_key = f"desc_{index}"
    description = request.form.get(desc_key, "")
    time_key = f"time_{index}"
    scheduled_time = request.form.get(time_key)
    # ---- Convert local time (PKT) to UTC ----
    from datetime import datetime
    local_tz = pytz.timezone("Asia/Karachi")  # Change to your timezone if different
    local_time = datetime.strptime(scheduled_time, "%Y-%m-%dT%H:%M")
    local_time = local_tz.localize(local_time)       # attach timezone info (PKT)
    utc_time = local_time.astimezone(pytz.UTC)       # convert to UTC
    scheduled_time_utc = utc_time.strftime("%Y-%m-%dT%H:%M")
    
    if not scheduled_time:
        return "Scheduled time is required", 400
    
    # ---- 1. Read the product ID from the hidden field ----
    product_id = request.form.get(f"product_id_{index}")
    
    # ---- 2. Find the provider ----
    provider = None
    for p in config.get("affiliate_providers", []):
        if p["nickname"] == provider_name:
            provider = p
            break
    
    # ---- 3. Fetch raw products (unfiltered) ----
    raw_products = []
    if provider:
        from src.utils.affiliate_api import search_products
        raw_products = search_products(provider, search_term)
    
    # ---- 4. Select product using product_id ----
    selected_product = {}
    if product_id:
        # Match by ID
        selected_product = next((p for p in raw_products if str(p.get("product_id", "")) == str(product_id)), {})
    
    # Fallback to index if not found (should not happen)
    if not selected_product and raw_products and index < len(raw_products):
        selected_product = raw_products[index]
    
    # ---- 5. Create the scheduled post ----
    new_post = {
        "id": str(uuid.uuid4())[:8],
        "page_id": page_id,
        "provider_name": provider_name,
        "search_term": search_term,
        "product_id": selected_product.get("product_id", ""),
        "product_name": selected_product.get("name", search_term),
        "product_image": selected_product.get("image_url", ""),
        "description_override": description,
        "scheduled_time": scheduled_time_utc,
        "posted": False,
        "fb_post_id": None,
        "video_url": request.form.get(f"video_url_{index}", ""),
        "has_video": request.form.get(f"has_video_{index}", "false").lower() == "true"
    }
    config["scheduled_affiliate_posts"].append(new_post)
    save_config(config)
    
    # ---- 6. Filter for display (hide scheduled) ----
    all_scheduled = config.get("scheduled_affiliate_posts", [])
    scheduled_ids = [p.get("product_id") for p in all_scheduled if p.get("product_id")]
    display_products = [p for p in raw_products if p.get("product_id") not in scheduled_ids]
    
    # ---- 7. Prepare and render ----
    providers = config.get("affiliate_providers", [])
    pages = config.get("pages", [])
    scheduled = [p for p in all_scheduled if not p.get("posted", False)]
    
    from datetime import datetime, timedelta
    default_time = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    
    return render_template_string(
        AFFILIATE_HTML,
        providers=providers,
        pages=pages,
        scheduled_posts=scheduled,
        search_results=display_products,
        current_page_id=page_id,
        current_provider=provider_name,
        default_time=default_time,
        search_term=search_term
    )

@app.route("/cancel_scheduled/<post_id>", methods=["POST"])
@requires_auth
def cancel_scheduled(post_id):
    config = load_config()
    config["scheduled_affiliate_posts"] = [p for p in config.get("scheduled_affiliate_posts", []) if p["id"] != post_id]
    save_config(config)
    return redirect(url_for("affiliate_dashboard"))

@app.route("/add_provider", methods=["POST"])
@requires_auth
def add_provider():
    config = load_config()
    if "affiliate_providers" not in config:
        config["affiliate_providers"] = []

    provider_id = str(uuid.uuid4())[:8]

    # Get user input
    provider_name = request.form.get("provider_name", "").strip().lower()
    api_key = request.form.get("api_key", "").strip()
    api_secret = request.form.get("api_secret", "").strip()
    associate_tag = request.form.get("associate_tag", "").strip()

    # Load drivers
    drivers = load_drivers()

    # Check if we have a driver for this provider
    if provider_name in drivers:
        provider_config = drivers[provider_name].copy()
        print(f"✅ Driver found for '{provider_name}'")
    else:
        print(f"⚠️ No driver found for '{provider_name}'. Saving basic config.")
        provider_config = {}

    # Inject user credentials
    provider_config["api_key"] = api_key
    provider_config["api_secret"] = api_secret
    provider_config["associate_tag"] = associate_tag

    # Replace placeholders in headers, static_params, and body_data
    if "headers" in provider_config:
        for key, value in provider_config["headers"].items():
            if isinstance(value, str):
                provider_config["headers"][key] = value.replace("{{api_secret}}", api_secret).replace("{{api_key}}", api_key)

    if "static_params" in provider_config:
        for key, value in provider_config["static_params"].items():
            if isinstance(value, str):
                provider_config["static_params"][key] = value.replace("{{associate_tag}}", associate_tag).replace("{{api_key}}", api_key)

    if "body_data" in provider_config:
        for key, value in provider_config["body_data"].items():
            if isinstance(value, str):
                provider_config["body_data"][key] = value.replace("{{associate_tag}}", associate_tag).replace("{{api_key}}", api_key)

    # Save everything
    new_provider = {
        "id": provider_id,
        "provider_type": provider_name,
        "nickname": request.form.get("provider_name", "").strip(),
        **provider_config
    }

    config["affiliate_providers"].append(new_provider)
    save_config(config)
    print(f"✅ Provider '{provider_name}' saved successfully.")
    return redirect(url_for("affiliate_dashboard"))

@app.route("/delete_provider/<provider_id>", methods=["POST"])
@requires_auth
def delete_provider(provider_id):
    config = load_config()
    config["affiliate_providers"] = [p for p in config.get("affiliate_providers", []) if p["id"] != provider_id]
    save_config(config)
    return redirect(url_for("affiliate_dashboard"))

@app.route("/toggle_pause", methods=["POST"])
@requires_auth
def toggle_pause():
    """Toggles the bot between paused and running states."""
    global BOT_PAUSED
    BOT_PAUSED = not BOT_PAUSED
    status = "paused" if BOT_PAUSED else "resumed"
    print(f"⏸️ Bot {status}")
    return redirect(url_for("index"))


# ===================== TEST & SCHEDULER (ROUND-ROBIN) =====================


@app.route("/test_post/<page_id>", methods=["POST"])
@requires_auth
def test_post(page_id):
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
    return redirect(url_for("index"))


@app.route("/run_scheduler")
def run_scheduler():
    """UptimeRobot hits this every 5 minutes."""
    config = load_config()
    now = time.time()
    pages = config.get("pages", [])

    for idx, p in enumerate(pages):
        # ---- Posting Logic ----
        if (now - p.get("last_posted", 0)) > (p["interval"] * 3600):
            print(f"⏰ Posting for {p['id']} (Index: {idx})")

            if idx % 2 == 0:
                print("🔄 Using Engine 1")
                run_engine_1(p)
            else:
                print("🔄 Using Engine 2")
                run_engine_2(p)

            p["last_posted"] = now
            save_config(config)
            time.sleep(10)

        # ---- Engagement Logic (once per 24 hours) ----
        engagement_interval = 24 * 3600
        if (now - p.get("last_engagement", 0)) > engagement_interval:
            print(f"🤝 Running engagement for {p['id']}")
            run_engagement(p)
            p["last_engagement"] = now
            save_config(config)
            time.sleep(5)

    # ---- NEW: Process scheduled affiliate posts ----
    process_affiliate_posts()

    return "Scheduler checked.", 200

def post_affiliate_product(scheduled_post, page):
    """
    Takes a scheduled affiliate post, fetches the product again,
    and uses the AI Engine to create a post based on the Page's Brief.
    """
    config = load_config()
    
    # 1. Find the provider
    provider = None
    for p in config.get("affiliate_providers", []):
        if p["nickname"] == scheduled_post["provider_name"]:
            provider = p
            break

    if not provider:
        print(f"❌ Provider '{scheduled_post['provider_name']}' not found.")
        return None

    # 2. Fetch products
    from src.utils.affiliate_api import search_products
    products = search_products(provider, scheduled_post["search_term"])
    if not products:
        print(f"❌ No products found for '{scheduled_post['search_term']}'.")
        return None

    # 3. Find the specific product using the stored product_id
    stored_product_id = scheduled_post.get("product_id")
    product = None
    if stored_product_id:
        product = next((p for p in products if str(p.get("product_id", "")) == str(stored_product_id)), None)
    
    # Fallback to first product if not found (should not happen)
    if not product:
        print(f"⚠️ Product with ID {stored_product_id} not found. Using first product as fallback.")
        product = products[0]

    # 4. Get the affiliate link (fallback to product URL if missing)
    affiliate_link = product.get('affiliate_link') or product.get('product_url', '')

    # ==============================================================
    # 5. Extract prices – only USD for display, but keep CNY for fallback
    # ==============================================================
    sale_usd = product.get('sale_price_usd', 'N/A')
    sale_cny = product.get('sale_price_cny', 'N/A')
    currency_usd = product.get('currency_usd', 'USD')
    currency_cny = product.get('currency_cny', 'CNY')

    original_usd = product.get('original_price_usd', 'N/A')
    original_cny = product.get('original_price_cny', 'N/A')

    # ---- Build a clean, eye‑catching price block (USD only) ----
    if sale_usd != 'N/A' and original_usd != 'N/A':
        try:
            sale = float(sale_usd)
            original = float(original_usd)
            if original > 0:
                discount = int(((original - sale) / original) * 100)
                price_display = f"💰 DEAL: {discount}% OFF!\n🪙 Now only ${sale:.2f} — was ${original:.2f}"
            else:
                price_display = f"🪙 Now only ${sale:.2f}"
        except:
            price_display = f"🪙 Now only ${sale_usd}"
    else:
        price_display = f"🪙 Now only ${sale_usd}"

    # (Keep the CNY values for logging, but we won't use them in the prompt)
    print(f"💰 Price (USD): {price_display}")
    print(f"💰 Original (CNY/USD): {original_cny} {currency_cny} (~{original_usd} {currency_usd})")

    # ==============================================================
    # 6. Build the AI prompt using the new structured format
    # ==============================================================
    product_name = product.get('name', 'Product')
    product_description = product.get('description', '')

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
- A catchy headline (use the product name or a hook)
- The price section (already provided in Price) – include it exactly as given.
- Bullet points highlighting key features (extract from product description if available, otherwise make reasonable assumptions)
- A call to action (e.g., "Grab yours now – limited stock!")
- End with the affiliate link on a new line.
- Do not include any extra text beyond the post.
"""

    # 7. Generate the post using AI (same as before)
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
            else:  # Gemini or others
                from google import genai
                model = get_model_name(provider_name) or "models/gemini-3.5-flash"
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model=model, contents=prompt
                )
                formatted_post = response.text.strip()
                break
        except Exception as e:
            print(f"⚠️ AI provider {provider_name} failed: {e}")
            continue

    # If AI generation fails, fallback to a simple message
    if not formatted_post:
        print("⚠️ AI generation failed. Using fallback message.")
        formatted_post = f"""🔥 NEW DEAL ALERT! 🇵🇰

🛍️ {product.get('name', 'Product')}
{price_display}

🔗 Grab it now: {affiliate_link}

#DealAlert #Pakistan #Shopping"""

    # 8. Post to Facebook
    from src.core.facebook_client import post_to_facebook, post_video_to_facebook, get_post_insights
    from src.engines.engine_1_urdu_poetry import log_performance
    
    print(f"📤 Posting to Facebook using AI-generated text...")
    
    # ---- Get video or image URL ----
    video_url = scheduled_post.get("video_url") or product.get("video_url") or product.get("product_video_url")
    image_url = scheduled_post.get("product_image") or product.get("image_url")

    # ---- Debug prints ----
    print(f"🔍 DEBUG: video_url = {video_url}")
    print(f"🔍 DEBUG: image_url = {image_url}")

    if video_url:
        print(f"🎬 Posting product video: {video_url[:100]}...")
        print(f"📹 Full video URL: {video_url}")
        post_id = post_video_to_facebook(
            page_id=page["id"],
            access_token=page["token"],
            caption=formatted_post,
            video_url=video_url
        )
        print(f"🔍 DEBUG: post_video_to_facebook returned: {post_id}")
    elif image_url:
        print(f"📸 Using image URL: {image_url[:100]}...")
        print(f"🖼️ Full image URL: {image_url}")
        post_id = post_to_facebook(
            access_token=page["token"],
            page_id=page["id"],
            message=formatted_post,
            image_url=image_url
        )
        print(f"🔍 DEBUG: post_to_facebook returned: {post_id}")
    else:
        print("⚠️ No image or video URL available. Posting text only.")
        post_id = post_to_facebook(
            access_token=page["token"],
            page_id=page["id"],
            message=formatted_post,
            image_url=None
        )

    # ---- Log performance for affiliate post ----
    if post_id:
        insights = get_post_insights(post_id, page["token"])
        log_performance(post_id, insights, page["id"])
        print(f"📊 Analytics logged for post: {post_id}")
    else:
        print("❌ No post ID returned – skipping analytics logging.")

    return post_id

def process_affiliate_posts():
    """Check and publish due affiliate posts."""
    config = load_config()
    scheduled_posts = config.get("scheduled_affiliate_posts", [])
    if not scheduled_posts:
        print("📋 No scheduled affiliate posts.")
        return

    now = time.time()
    for post in scheduled_posts:
        if post.get("posted"):
            continue
        try:
            from datetime import datetime
            post_time = datetime.strptime(post["scheduled_time"], "%Y-%m-%dT%H:%M")
            if now >= post_time.timestamp():
                print(f"⏰ Affiliate post due for: {post.get('search_term', 'No term')}")
                page = next((p for p in config.get("pages", []) if p["id"] == post["page_id"]), None)
                if not page:
                    print(f"❌ Page {post['page_id']} not found.")
                    post["posted"] = True
                    save_config(config)
                    continue
                post_id = post_affiliate_product(post, page)
                if post_id:
                    config["scheduled_affiliate_posts"] = [p for p in config.get("scheduled_affiliate_posts", []) if p["id"] != post["id"]]
                    print(f"✅ Affiliate post published! ID: {post_id}")
                else:
                    print(f"❌ Failed to post affiliate product. Will retry later.")
                save_config(config)
        except Exception as e:
            print(f"⚠️ Error processing scheduled post {post.get('id', 'unknown')}: {e}")
            import traceback
            traceback.print_exc()

# --- Background Scheduler (Round-Robin) ---
def bot_scheduler():
    print("🟢 Bot scheduler started! Running every 60 seconds.")
    while True:
        print(f"🔄 Scheduler loop running at {time.strftime('%H:%M:%S')}")
        
        # ---- Check if bot is paused ----
        if BOT_PAUSED:
            print("⏸️ Bot is paused. Waiting...")
            time.sleep(30)
            continue

        config = load_config()
        now = time.time()
        pages = config.get("pages", [])
        
        for idx, p in enumerate(pages):
            # ---- Posting Logic ----
            if (now - p.get("last_posted", 0)) > (p["interval"] * 3600):
                print(f"⏰ Posting for {p['id']} (Index: {idx})")

                if idx % 2 == 0:
                    print("🔄 Using Engine 1")
                    run_engine_1(p)
                else:
                    print("🔄 Using Engine 2")
                    run_engine_2(p)

                p["last_posted"] = now
                save_config(config)
                time.sleep(10)

            # ---- Engagement Logic (once per 24 hours) ----
            engagement_interval = 24 * 3600
            if (now - p.get("last_engagement", 0)) > engagement_interval:
                print(f"🤝 Running engagement for {p['id']}")
                run_engagement(p)
                p["last_engagement"] = now
                save_config(config)
                time.sleep(5)

        # ---- Check Scheduled Affiliate Posts ----
        config = load_config()
        scheduled_posts = config.get("scheduled_affiliate_posts", [])
        print(f"📋 Found {len(scheduled_posts)} scheduled affiliate posts")
        now = time.time()
        
        for post in scheduled_posts:
            if post.get("posted") == True:
                print(f"⏭️ Skipping already posted post: {post.get('id', 'unknown')}")
                continue
            
            try:
                from datetime import datetime
                post_time = datetime.strptime(post["scheduled_time"], "%Y-%m-%dT%H:%M")
                post_timestamp = post_time.timestamp()
                print(f"🔍 Checking post: {post.get('search_term', 'No term')[:30]}... due at {post['scheduled_time']}")
                print(f"   ➡️ Time difference: {post_timestamp - now:.0f} seconds")
                
                if now >= post_timestamp:
                    print(f"⏰ Affiliate post due for: {post.get('search_term', 'No term')}")
                    
                    # Find the page
                    page = None
                    for p in config.get("pages", []):
                        if p["id"] == post["page_id"]:
                            page = p
                            break
                    
                    if not page:
                        print(f"❌ Page {post['page_id']} not found.")
                        post["posted"] = True
                        save_config(config)
                        continue
                    
                    print("📤 Calling post_affiliate_product...")
                    post_id = post_affiliate_product(post, page)
                    
                    if post_id:
                        # Remove from queue instead of just marking as posted
                        config["scheduled_affiliate_posts"] = [p for p in config.get("scheduled_affiliate_posts", []) if p["id"] != post["id"]]
                        print(f"✅ Affiliate post published! ID: {post_id} (Removed from queue)")
                    else:
                        print(f"❌ Failed to post affiliate product. Will retry later.")
                    save_config(config)
                    
            except Exception as e:
                print(f"⚠️ Error processing scheduled post {post.get('id', 'unknown')}: {e}")
                import traceback
                traceback.print_exc()

        time.sleep(60)


# --- Launcher ---
if __name__ == "__main__":
    print("🚀 Vigil AI Desktop App starting...")
    
    # Load config for Telegram
    config = load_config()
    telegram_token = config.get("telegram_bot_token", "")
    if telegram_token:
        try:
            from src.core.telegram_bot import start_telegram_bot
            start_telegram_bot(telegram_token)
        except AttributeError as e:
            if "_Updater__polling_cleanup_cb" in str(e):
                print("⚠️ Telegram library conflict detected. Skipping Telegram.")
            else:
                print(f"❌ Telegram bot failed to start: {e}")
        except Exception as e:
            print(f"❌ Telegram bot failed to start: {e}")
    else:
        print("ℹ️ No Telegram token found. Skipping Telegram.")
    
    threading.Thread(target=bot_scheduler, daemon=True).start()
    import webbrowser, time
    def open_browser():
        time.sleep(1.5)
        webbrowser.open("http://127.0.0.1:5000")
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)