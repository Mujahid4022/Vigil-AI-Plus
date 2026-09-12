"""
tts_processor.py - Universal Text-to-Speech engine.
Provider-agnostic. Configuration-driven (like voice_processor.py).
"""
import os
import json
import tempfile


DRIVER_FILE = "src/utils/tts_drivers.json"


def load_tts_drivers():
    if os.path.exists(DRIVER_FILE):
        with open(DRIVER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def synthesize_speech(text: str, language: str = "en", provider_name: str = "gtts") -> str:
    """
    Convert text to speech. Returns path to an .mp3 file, or "" on failure.

    Args:
        text: text to speak
        language: 'ur' or 'en'
        provider_name: key from tts_drivers.json
    """
    if not text or not text.strip():
        return ""

    drivers = load_tts_drivers()
    driver = drivers.get(provider_name)
    if not driver:
        print(f"❌ No TTS driver for '{provider_name}'")
        return ""

    provider_type = driver.get("provider_type", "gtts")

    try:
        if provider_type == "gtts":
            return _synthesize_gtts(text, language, driver)
        elif provider_type == "edge":
            return _synthesize_edge(text, language, driver)
        else:
            print(f"❌ Unknown TTS provider type: {provider_type}")
            return ""
    except Exception as e:
        print(f"❌ TTS error ({provider_name}): {e}")
        return ""


def _synthesize_gtts(text: str, language: str, driver: dict) -> str:
    """Generate MP3 using Google TTS (free, no API key)."""
    from gtts import gTTS

    lang_map = driver.get("lang_map", {"ur": "ur", "en": "en"})
    target_lang = lang_map.get(language, "en")

    # Clean text — remove markdown, emojis mess up TTS
    clean_text = _clean_for_tts(text)
    if not clean_text:
        return ""

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tmp.close()

    tts = gTTS(text=clean_text, lang=target_lang, slow=driver.get("slow", False))
    tts.save(tmp.name)

    print(f"🔊 TTS generated ({target_lang}): {tmp.name}")
    return tmp.name


def _synthesize_edge(text: str, language: str, driver: dict) -> str:
    """Placeholder for Edge TTS (optional)."""
    # Requires: pip install edge-tts
    import edge_tts
    import asyncio

    voice_map = driver.get("voice_map", {"ur": "ur-PK-AsadNeural", "en": "en-US-GuyNeural"})
    voice = voice_map.get(language, "en-US-GuyNeural")

    clean_text = _clean_for_tts(text)
    if not clean_text:
        return ""

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tmp.close()

    async def _go():
        communicate = edge_tts.Communicate(clean_text, voice)
        await communicate.save(tmp.name)

    asyncio.run(_go())
    print(f"🔊 Edge TTS generated: {tmp.name}")
    return tmp.name


def _clean_for_tts(text: str) -> str:
    """Strip markdown / emojis / long URLs so TTS sounds natural."""
    import re

    # Remove URLs
    text = re.sub(r'https?://\S+', '', text)
    # Remove markdown bold/italic/code
    text = re.sub(r'[*_`#]+', '', text)
    # Remove emojis (broad range)
    text = re.sub(r'[\U0001F300-\U0001FAFF\U00002700-\U000027BF]+', '', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text