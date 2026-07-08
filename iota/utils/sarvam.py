"""
Sarvam AI wrapper using aiohttp directly (no sarvamai package needed)
Works on Termux without Rust/pydantic-core
"""
import aiohttp
import base64
import logging
from config import SARVAM_API_KEY

logger = logging.getLogger(__name__)

CHAT_URL = "https://api.sarvam.ai/v1/chat/completions"
TTS_URL  = "https://api.sarvam.ai/text-to-speech"
TRANSLATE_URL = "https://api.sarvam.ai/translate"

# Valid bulbul:v2 speakers (Sarvam's current, supported TTS model).
# Kept here as the single source of truth for validation in the owner
# settings panel — see handlers/owner_panel.py's /ttssettings.
VALID_SPEAKERS = ["anushka", "manisha", "vidya", "arya", "abhilash", "karun", "hitesh"]
VALID_MODELS = ["bulbul:v2"]  # bulbul:v1 is fully deprecated — never offer it

# ── Owner-configurable TTS defaults ─────────────────────────────────────────
# Mirrors utils/ai_provider.py's model-config pattern: an in-memory dict
# the owner can change via bot commands, persisted to MongoDB so it
# survives restarts. Applied as the DEFAULT for every /voice request —
# individual calls can still override any of these per-call if needed.
_tts_config = {
    "model": "bulbul:v2",
    "speaker": "anushka",
    "pace": 1.0,       # 0.5 (slow) - 2.0 (fast) per Sarvam's documented range
    "pitch": 0,        # -20 to 20
    "loudness": 1.5,   # 0.5 - 2.0
}


def get_tts_config() -> dict:
    return dict(_tts_config)


def set_tts_setting(key: str, value) -> tuple[bool, str]:
    """Validates and applies one TTS setting. Returns (ok, error_message)."""
    if key == "speaker":
        if value not in VALID_SPEAKERS:
            return False, f"Invalid speaker. Valid: {', '.join(VALID_SPEAKERS)}"
        _tts_config["speaker"] = value
    elif key == "model":
        if value not in VALID_MODELS:
            return False, f"Invalid model. Valid: {', '.join(VALID_MODELS)} (bulbul:v1 is deprecated, never usable)"
        _tts_config["model"] = value
    elif key == "pace":
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False, "Pace must be a number (e.g. 1.0)"
        if not (0.5 <= v <= 2.0):
            return False, "Pace must be between 0.5 (slow) and 2.0 (fast)"
        _tts_config["pace"] = v
    elif key == "pitch":
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False, "Pitch must be a number (e.g. 0)"
        if not (-20 <= v <= 20):
            return False, "Pitch must be between -20 and 20"
        _tts_config["pitch"] = v
    elif key == "loudness":
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False, "Loudness must be a number (e.g. 1.5)"
        if not (0.5 <= v <= 2.0):
            return False, "Loudness must be between 0.5 and 2.0"
        _tts_config["loudness"] = v
    else:
        return False, f"Unknown setting '{key}'. Valid keys: model, speaker, pace, pitch, loudness"
    return True, ""


async def save_tts_config_db():
    """Persist current TTS settings so they survive a bot restart."""
    from utils.mongo_db import get_db
    await get_db().bot_config.update_one(
        {"_id": "tts_settings"}, {"$set": _tts_config}, upsert=True
    )


async def load_tts_config_db():
    """Load TTS settings from DB on startup."""
    from utils.mongo_db import get_db
    doc = await get_db().bot_config.find_one({"_id": "tts_settings"})
    if doc:
        for k in ("model", "speaker", "pace", "pitch", "loudness"):
            if k in doc:
                _tts_config[k] = doc[k]


async def chat(messages: list, model="sarvam-m", max_tokens=300, temperature=0.9) -> str:
    """Chat completion via Sarvam AI."""
    headers = {
        "api-subscription-key": SARVAM_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(CHAT_URL, json=payload, headers=headers,
                          timeout=aiohttp.ClientTimeout(total=25)) as r:
            if r.status == 200:
                d = await r.json()
                return d["choices"][0]["message"]["content"].strip()
            err = await r.text()
            raise Exception(f"Sarvam API {r.status}: {err[:100]}")


async def translate(text: str, target_lang: str = "en-IN",
                    source_lang: str = "auto") -> str:
    """Translate text using Sarvam AI."""
    headers = {
        "api-subscription-key": SARVAM_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "input": text,
        "source_language_code": source_lang,
        "target_language_code": target_lang,
        "speaker_gender": "Female",
        "mode": "formal",
        "model": "mayura:v1",
        "enable_preprocessing": True
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(TRANSLATE_URL, json=payload, headers=headers,
                          timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 200:
                d = await r.json()
                return d.get("translated_text", text)
            # Fallback to chat-based translation
            return await chat([
                {"role": "system", "content": f"Translate to {target_lang}. Return ONLY translated text."},
                {"role": "user", "content": text}
            ], max_tokens=200)


async def text_to_speech(text: str, lang: str = "hi-IN",
                         speaker: str = None) -> bytes | None:
    """
    Convert text to speech, returns wav bytes or None.

    Uses the owner-configured defaults (model/speaker/pace/pitch/
    loudness — see get_tts_config()/set_tts_setting() above, managed via
    /ttssettings in the owner panel) unless a specific `speaker` is
    passed in to override just that one value for this call.

    🔴 FIXED (this used to be permanently broken): previously hardcoded
    model="bulbul:v1" (fully deprecated by Sarvam, guaranteed failure on
    every call) and speaker="meera" (never a valid speaker for any
    Sarvam TTS model). Now defaults to bulbul:v2 with a real, valid voice.
    """
    cfg = get_tts_config()
    headers = {
        "api-subscription-key": SARVAM_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "inputs": [text[:500]],
        "target_language_code": lang,
        "speaker": speaker or cfg["speaker"],
        "pitch": cfg["pitch"],
        "pace": cfg["pace"],
        "loudness": cfg["loudness"],
        "speech_sample_rate": 22050,
        "enable_preprocessing": True,
        "model": cfg["model"]
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(TTS_URL, json=payload, headers=headers,
                          timeout=aiohttp.ClientTimeout(total=30)) as r:
            if r.status == 200:
                d = await r.json()
                audios = d.get("audios", [])
                if audios:
                    return base64.b64decode(audios[0])
            else:
                # Log the actual failure reason instead of silently
                # returning None — this is exactly what made the old
                # bulbul:v1 failure invisible/undebuggable.
                err = await r.text()
                logger.warning(f"Sarvam TTS failed ({r.status}): {err[:200]}")
            return None
