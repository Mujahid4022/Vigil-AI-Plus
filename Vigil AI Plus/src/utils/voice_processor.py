"""
voice_processor.py - Universal voice transcription engine.
Provider-agnostic. Configuration-driven (like affiliate_api.py).
"""
import os
import json
import httpx
from config.config import get_api_key


DRIVER_FILE = "src/utils/voice_drivers.json"


def load_voice_drivers():
    if os.path.exists(DRIVER_FILE):
        with open(DRIVER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _map_language(detected: str) -> str:
    """Normalize provider language codes to 'ur' or 'en'."""
    if not detected:
        return "en"
    d = detected.lower().strip()
    if d in ("urdu", "ur", "ur-pk", "ur_in"):
        return "ur"
    if d in ("english", "en", "en-us", "en-gb"):
        return "en"
    return d[:2]  # fallback


async def transcribe_voice(audio_path: str, provider_name: str = "groq", language: str = None) -> dict:
    """
    Transcribe audio using the specified provider driver.
    language=None → auto-detect.

    Returns: {"text": str, "language": "ur|en", "provider": str}
             or {} on failure.
    """
    drivers = load_voice_drivers()
    driver = drivers.get(provider_name)
    if not driver:
        print(f"❌ No voice driver for '{provider_name}'")
        return {}

    api_key = get_api_key(driver.get("api_key_source", provider_name))
    if not api_key:
        print(f"❌ No API key for '{driver.get('api_key_source')}'")
        return {}

    if not os.path.exists(audio_path):
        print(f"❌ Audio file not found: {audio_path}")
        return {}

    provider_type = driver.get("provider_type", "openai_compatible")

    try:
        if provider_type == "openai_compatible":
            return await _transcribe_openai_compatible(audio_path, driver, api_key, language)
        elif provider_type == "deepgram":
            return await _transcribe_deepgram(audio_path, driver, api_key, language)
        else:
            print(f"❌ Unknown voice provider type: {provider_type}")
            return {}
    except Exception as e:
        print(f"❌ Voice transcription error ({provider_name}): {e}")
        return {}


async def _transcribe_openai_compatible(audio_path, driver, api_key, language):
    async with httpx.AsyncClient(timeout=60) as client:
        with open(audio_path, "rb") as audio:
            files = {"file": (os.path.basename(audio_path), audio, "audio/ogg")}
            data = {
                "model": driver["model"],
                "response_format": driver.get("response_format", "verbose_json"),
            }
            if language:
                data["language"] = language

            response = await client.post(
                driver["base_url"],
                headers={"Authorization": f"Bearer {api_key}"},
                files=files,
                data=data,
            )

    if response.status_code != 200:
        print(f"❌ STT error {response.status_code}: {response.text[:200]}")
        return {}

    result = response.json()
    text = (result.get("text") or "").strip()
    detected = result.get("language") or "en"
    lang = _map_language(detected)

    if text:
        print(f"🎤 Transcribed ({lang}): {text[:80]}")
        return {"text": text, "language": lang, "provider": "openai_compatible"}

    return {}


async def _transcribe_deepgram(audio_path, driver, api_key, language):
    """Placeholder for future Deepgram support."""
    async with httpx.AsyncClient(timeout=60) as client:
        with open(audio_path, "rb") as audio:
            params = {"model": driver.get("model", "nova-2"), "smart_format": "true"}
            if language:
                params["language"] = language

            response = await client.post(
                driver["base_url"],
                headers={
                    "Authorization": f"Token {api_key}",
                    "Content-Type": "audio/ogg",
                },
                params=params,
                content=audio.read(),
            )

    if response.status_code != 200:
        print(f"❌ Deepgram error {response.status_code}: {response.text[:200]}")
        return {}

    result = response.json()
    try:
        text = result["results"]["channels"][0]["alternatives"][0]["transcript"]
        lang = _map_language(result.get("results", {}).get("channels", [{}])[0].get("detected_language", "en"))
        return {"text": text.strip(), "language": lang, "provider": "deepgram"}
    except (KeyError, IndexError):
        return {}