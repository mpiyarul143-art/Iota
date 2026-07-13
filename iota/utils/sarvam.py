"""
Sarvam AI wrapper using aiohttp directly (no sarvamai package needed)
Works on Termux without Rust/pydantic-core

NOTE: Text-to-speech moved to ``utils/tts_engine.py`` (modern Bulbul v3 engine
with auto-fetched voices + voice cloning). This module now only handles chat
completions and translation. Import TTS symbols from ``utils/tts_engine``.
"""
import aiohttp
import logging
from config import SARVAM_API_KEY

logger = logging.getLogger(__name__)

CHAT_URL = "https://api.sarvam.ai/v1/chat/completions"
TRANSLATE_URL = "https://api.sarvam.ai/translate"


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
