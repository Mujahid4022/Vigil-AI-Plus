"""
twitter_client.py - Twitter API wrapper for Vigil AI.
"""

import tweepy
import os
import requests
from io import BytesIO


def get_twitter_api(consumer_key, consumer_secret, access_token, access_token_secret):
    """Authenticate and return the Tweepy API client."""
    auth = tweepy.OAuth1UserHandler(
        consumer_key, consumer_secret, access_token, access_token_secret
    )
    return tweepy.API(auth)


def post_to_twitter(
    consumer_key: str,
    consumer_secret: str,
    access_token: str,
    access_token_secret: str,
    text: str,
    image_url: str = None,
    image_path: str = None,
) -> str:
    """
    Posts a tweet (with optional image) to Twitter.
    Returns the tweet ID if successful, else None.
    """
    try:
        api = get_twitter_api(
            consumer_key, consumer_secret, access_token, access_token_secret
        )

        # Trim text to Twitter's limit (280 chars)
        if len(text) > 280:
            text = text[:277] + "..."

        if image_url:
            # Download image from URL
            response = requests.get(image_url)
            img_data = BytesIO(response.content)
            media = api.media_upload(filename="image.jpg", file=img_data)
            result = api.update_status(status=text, media_ids=[media.media_id])
        elif image_path and os.path.exists(image_path):
            media = api.media_upload(filename=image_path)
            result = api.update_status(status=text, media_ids=[media.media_id])
        else:
            result = api.update_status(status=text)

        tweet_id = result.id_str
        print(f"✅ Tweet posted! ID: {tweet_id}")
        return tweet_id
    except Exception as e:
        print(f"❌ Twitter error: {e}")
        return None