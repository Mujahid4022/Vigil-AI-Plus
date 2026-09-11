"""
engine_engagement.py - Engages with followers by liking and commenting on posts.
Also tracks leads (users who comment or like) for CRM/email integration.
"""

import requests
import time
import random
import json
import os
from config.config import get_page_token
from src.core.facebook_client import like_post, comment_on_post
from src.core.lead_tracker import track_lead

# ----------------------------------------------------------------------
# Helper: Fetch recent posts from a page
# ----------------------------------------------------------------------
def fetch_recent_posts(page_id, page_token, limit=5):
    """Fetches the most recent posts from the page."""
    url = f"https://graph.facebook.com/v26.0/{page_id}/posts?access_token={page_token}&limit={limit}"
    response = requests.get(url)
    return response.json().get('data', [])

# ----------------------------------------------------------------------
# Helper: Fetch comments on a post
# ----------------------------------------------------------------------
def fetch_comments(post_id, page_token, limit=20):
    """Fetches comments on a post."""
    url = f"https://graph.facebook.com/v26.0/{post_id}/comments?access_token={page_token}&limit={limit}"
    response = requests.get(url)
    return response.json().get('data', [])

# ----------------------------------------------------------------------
# Helper: Fetch likes on a post
# ----------------------------------------------------------------------
def fetch_likes(post_id, page_token, limit=20):
    """Fetches likes on a post."""
    url = f"https://graph.facebook.com/v26.0/{post_id}/likes?access_token={page_token}&limit={limit}"
    response = requests.get(url)
    return response.json().get('data', [])

# ----------------------------------------------------------------------
# Main Engagement Engine
# ----------------------------------------------------------------------
def run_engagement(page):
    """
    Likes and comments on recent posts from the page's feed.
    Tracks commenters and likers as leads.
    Should be run once a day to avoid rate limits.
    """
    print(f"🤝 [Engagement] Running for Page: {page['id']}")

    page_id = page['id']
    token = page['token']

    # 1. Fetch recent posts
    posts = fetch_recent_posts(page_id, token, limit=10)
    if not posts:
        print("⚠️ No posts found to engage with.")
        return

    # 2. Interact with each post and track leads
    for post in posts:
        post_id = post['id']
        try:
            # ---- Fetch comments on this post ----
            comments = fetch_comments(post_id, token, limit=20)
            for comment in comments:
                commenter = comment.get('from', {})
                user_id = commenter.get('id')
                name = commenter.get('name', 'Unknown')
                if user_id and user_id != page_id:  # avoid tracking the page itself
                    track_lead(
                        page_id=page_id,
                        user_id=user_id,
                        name=name,
                        message=comment.get('message', ''),
                        lead_type='comment',
                        webhook_url=page.get('lead_webhook_url')  # <-- Added
                    )

            # ---- Fetch likes on this post ----
            likes = fetch_likes(post_id, token, limit=20)
            for like in likes:
                user_id = like.get('id')
                name = like.get('name', 'Unknown')
                if user_id and user_id != page_id:
                    track_lead(
                        page_id=page_id,
                        user_id=user_id,
                        name=name,
                        message='Liked a post',
                        lead_type='like',
                        webhook_url=page.get('lead_webhook_url')  # <-- Added
                    )

            # ---- Like the post (50% chance) ----
            if random.random() > 0.3:
                like_post(post_id, token)
                time.sleep(random.randint(2, 5))

            # ---- Comment on the post (20% chance) ----
            if random.random() > 0.8:
                comment_text = random.choice([
                    "❤️ Love this!",
                    "🙌 Great post!",
                    "👏 Amazing content!",
                    "✨ Keep it up!",
                    "🌟 Fantastic!"
                ])
                comment_on_post(post_id, comment_text, token)
                time.sleep(random.randint(3, 7))

        except Exception as e:
            print(f"⚠️ Error engaging with post {post_id}: {e}")

    print("✅ [Engagement] Finished.")