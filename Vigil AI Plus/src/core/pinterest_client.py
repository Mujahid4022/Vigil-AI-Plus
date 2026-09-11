"""
pinterest_client.py - Native Pinterest API Wrapper for Vigil AI.
Handles automated posting of affiliate images, descriptions, and destination links.
"""

import requests
import json
import logging

# Optional: Configure logging if you have a logger set up
logger = logging.getLogger(__name__)


def post_to_pinterest(access_token, board_id, title, description, image_url, affiliate_link):
    """
    Posts a product pin natively to a specific Pinterest Board.

    Args:
        access_token (str): Your Pinterest Developer Access Token.
        board_id (str): The unique ID of your specific board folder.
        title (str): Clean product title name.
        description (str): Text captions with trending tags.
        image_url (str): Publicly accessible image address from AliExpress.
        affiliate_link (str): Your target tracking commission link.

    Returns:
        str: The Pin ID if successful, None otherwise.
    """
    # --- 1. Input Validation (Fail Fast) ---
    if not access_token:
        logger.error("Pinterest Access Token is missing.")
        return None
    if not board_id:
        logger.error("Pinterest Board ID is missing.")
        return None
    if not title or not description:
        logger.warning("Title or Description is empty.")
    if not image_url:
        logger.error("Image URL is required to create a Pin.")
        return None
    if not affiliate_link:
        logger.error("Affiliate Link is required.")
        return None

    # --- 2. Correct API Endpoint (V5) ---
    api_endpoint = "https://api.pinterest.com/v5/pins"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # --- 3. Prepare Payload with Pinterest Constraints ---
    payload = {
        "link": affiliate_link,
        "title": title[:100],          # Strict cap: 100 characters
        "description": description[:500],  # Strict cap: 500 characters
        "board_id": str(board_id),
        "media_source": {
            "source_type": "image_url",
            "url": image_url
        }
    }

    try:
        # Use `json=` instead of `data=` to let requests handle serialization
        response = requests.post(api_endpoint, headers=headers, json=payload, timeout=30)

        # --- 4. Correct Status Code Check ---
        if response.status_code in (200, 201):
            result = response.json()
            pin_id = result.get("id")
            logger.info(f"✅ Pinterest Pin successfully published! Pin ID: {pin_id}")
            return pin_id
        else:
            # Log the full error response for debugging
            error_detail = response.text
            logger.error(f"❌ Pinterest API Error {response.status_code}: {error_detail}")
            
            # Optional: Try to parse API error message
            try:
                error_json = response.json()
                if "message" in error_json:
                    logger.error(f"Message: {error_json['message']}")
            except:
                pass  # Ignore if response isn't valid JSON
            return None

    except requests.exceptions.Timeout:
        logger.error("❌ Request timed out while connecting to Pinterest API.")
        return None
    except requests.exceptions.ConnectionError:
        logger.error("❌ Connection error while reaching Pinterest API.")
        return None
    except Exception as e:
        logger.error(f"❌ Critical exception encountered during Pinterest posting: {e}")
        return None