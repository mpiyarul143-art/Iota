"""
Sarvam AI wrapper using aiohttp directly (no sarvamai package needed)
Works on Termux without Rust/pydantic-core
"""
import aiohttp
import base64
from config import SARVAM_API_KEY

CHAT_URL = "https://api.sarvam.ai/v1/chat/completions"
TTS_URL  = "https://api.sarvam.ai/text-to-speech"
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


async def text_to_speech(text: str, lang: str = "hi-IN",
                         speaker: str = "meera") -> bytes | None:
    """Convert text to speech, returns wav bytes or None."""
    headers = {
        "api-subscription-key": SARVAM_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "inputs": [text[:500]],
        "target_language_code": lang,
        "speaker": speaker,
        "pitch": 0,
        "pace": 1.0,
        "loudness": 1.5,
        "speech_sample_rate": 22050,
        "enable_preprocessing": True,
        "model": "bulbul:v1"
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(TTS_URL, json=payload, headers=headers,
                          timeout=aiohttp.ClientTimeout(total=30)) as r:
            if r.status == 200:
                d = await r.json()
                audios = d.get("audios", [])
                if audios:
                    return base64.b64decode(audios[0])
            return None
