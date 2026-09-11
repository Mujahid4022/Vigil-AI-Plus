"""
text_processor.py - Urdu text shaping and Gemini AI integration (New SDK).
Uses dynamic model names from config.json.
"""

import arabic_reshaper
from bidi.algorithm import get_display
from google import genai
from config.config import get_api_key, get_model_name


# ----------------------------------------------------------------------
# 1. Reshape Urdu text for display on images
# ----------------------------------------------------------------------
def reshape_urdu_text(text: str) -> str:
    reshaped = arabic_reshaper.reshape(text)
    bidi_text = get_display(reshaped)
    return bidi_text


# ----------------------------------------------------------------------
# 2. Generate Urdu poetry using Gemini (Dynamic model)
# ----------------------------------------------------------------------
def generate_urdu_poetry(prompt: str = None) -> str:
    if not prompt:
        prompt = "Write a short, original Urdu poem of 4-6 lines about love, nature, or hope. Only return the poem text, no explanations."

    # Fetch API key and model name dynamically
    api_key = get_api_key("gemini")
    model = get_model_name("gemini") or "models/gemini-3.5-flash"

    if not api_key:
        print("❌ Gemini API key not found in config.json.")
        return None

    try:
        client = genai.Client(api_key=api_key)
        print(f"🧠 Gemini ({model})...")
        response = client.models.generate_content(model=model, contents=prompt)
        return response.text.strip()
    except Exception as e:
        print(f"❌ Gemini error: {e}")
        return None


# ----------------------------------------------------------------------
# Test (when run directly)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    poem = generate_urdu_poetry()
    if poem:
        print(poem)
    else:
        print("Failed to generate poem.")
