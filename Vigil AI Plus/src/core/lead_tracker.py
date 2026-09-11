"""
lead_tracker.py - Tracks leads from Facebook engagement.
"""

import csv
import os
import requests
import json
from datetime import datetime


def export_to_csv(lead_data, filename="leads.csv"):
    """Appends a lead to a CSV file."""
    file_exists = os.path.isfile(filename)
    with open(filename, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "page_id", "user_id", "name", "message", "type"])
        writer.writerow([
            datetime.now().isoformat(),
            lead_data.get("page_id", ""),
            lead_data.get("user_id", ""),
            lead_data.get("name", ""),
            lead_data.get("message", ""),
            lead_data.get("type", "comment"),
        ])
        print(f"✅ Lead saved to {filename}")


def send_to_webhook(webhook_url, lead_data):
    """Sends lead data to a webhook (e.g., Zapier, Mailchimp, HubSpot)."""
    try:
        response = requests.post(webhook_url, json=lead_data, timeout=10)
        if response.status_code in [200, 201, 202]:
            print(f"✅ Lead sent to webhook: {webhook_url}")
            return True
        else:
            print(f"❌ Webhook error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Webhook connection error: {e}")
        return False


def track_lead(page_id, user_id, name, message, lead_type="comment", webhook_url=None):
    """
    Main function to track a lead.
    Saves to CSV and optionally sends to a webhook.
    """
    lead_data = {
        "page_id": page_id,
        "user_id": user_id,
        "name": name or "Unknown",
        "message": message,
        "type": lead_type,
    }
    export_to_csv(lead_data)

    # Use provided webhook_url, else fallback to global from config.json
    if not webhook_url:
        CONFIG_FILE = "config.json"
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
            webhook_url = config.get("lead_webhook_url", "")
    
    if webhook_url:
        send_to_webhook(webhook_url, lead_data)