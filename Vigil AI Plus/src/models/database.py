"""
database.py - SQLite database for Vigil AI.

This module stores a history of all posts made by both engines.
It prevents reposting the same content and helps track performance.
"""

import sqlite3
import hashlib
import json
from datetime import datetime
from pathlib import Path

# Import the database path from config
from config.config import DATABASE_PATH

# ----------------------------------------------------------------------
# 1. Ensure the database directory exists
# ----------------------------------------------------------------------
db_dir = Path(DATABASE_PATH).parent
db_dir.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------------
# 2. Helper to get a database connection
# ----------------------------------------------------------------------
def get_connection():
    """
    Returns a connection to the SQLite database.
    Creates the database file if it doesn't exist.
    """
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row  # Allows accessing columns by name
    return conn


# ----------------------------------------------------------------------
# 3. Create the posts table if it doesn't exist
# ----------------------------------------------------------------------
def init_db():
    """
    Creates the 'posts' table with the required schema.
    Call this once when the application starts.
    """
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                engine_type TEXT NOT NULL,          -- 'urdu' or 'deals'
                content_hash TEXT NOT NULL UNIQUE,  -- hash of the post text
                content_text TEXT,                  -- original text (optional)
                posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fb_post_id TEXT                    -- Facebook post ID if available
            )
        """)
        conn.commit()


# ----------------------------------------------------------------------
# 4. Check if a post already exists (by content hash)
# ----------------------------------------------------------------------
def post_exists(content_text: str) -> bool:
    """
    Given the text of a post, compute its hash and check if it's already
    in the database. Returns True if it exists, False otherwise.
    """
    content_hash = hashlib.sha256(content_text.encode("utf-8")).hexdigest()
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT 1 FROM posts WHERE content_hash = ?", (content_hash,)
        )
        return cursor.fetchone() is not None


# ----------------------------------------------------------------------
# 5. Record a new post in the database
# ----------------------------------------------------------------------
def add_post(engine_type: str, content_text: str, fb_post_id: str = None):
    """
    Inserts a new post into the history.
    - engine_type: 'urdu' or 'deals'
    - content_text: the full text that was posted
    - fb_post_id: optional Facebook ID of the post
    """
    content_hash = hashlib.sha256(content_text.encode("utf-8")).hexdigest()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO posts (engine_type, content_hash, content_text, fb_post_id)
            VALUES (?, ?, ?, ?)
        """,
            (engine_type, content_hash, content_text, fb_post_id),
        )
        conn.commit()


# ----------------------------------------------------------------------
# 6. Get the latest posts (for debugging)
# ----------------------------------------------------------------------
def get_recent_posts(limit: int = 10):
    """
    Returns the most recent posts, ordered by posted_at descending.
    Useful for checking what has been posted.
    """
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM posts
            ORDER BY posted_at DESC
            LIMIT ?
        """,
            (limit,),
        )
        return cursor.fetchall()


# ----------------------------------------------------------------------
# 7. (Optional) Clear history – use with caution
# ----------------------------------------------------------------------
def clear_history():
    """Deletes all records from the posts table (for testing only)."""
    with get_connection() as conn:
        conn.execute("DELETE FROM posts")
        conn.commit()


# ----------------------------------------------------------------------
# 8. Initialize the database when this module is imported
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # When run directly, create the table and show a sample
    init_db()
    print("✅ Database initialized at:", DATABASE_PATH)
    print("Sample: Add a dummy post")
    add_post("urdu", "This is a test Urdu poem", "fb_123")
    print("Recent posts:")
    for row in get_recent_posts():
        print(dict(row))
