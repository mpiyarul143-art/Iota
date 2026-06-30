"""
Iota AI Provider System
- Free users: Kilo.ai free models (stepfun/step-3.7-flash:free, nvidia/nemotron etc)
- Premium users: x666.me premium models (grok-4.3-high, gpt-5.5-nx etc)
- Owner can switch which model each tier uses via /setmodel command
- Auto-fallback if model fails
"""
import aiohttp
import json
from utils.mongo_db import get_db

# ── Provider configs ──────────────────────────────────────────────────────────

KILO_BASE    = "https://api.kilo.ai/api/gateway/"
KILO_KEY     = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbnYiOiJwcm9kdWN0aW9uIiwia2lsb1VzZXJJZCI6ImEyMzE2Njk0LTM1MWYtNGI3Ny1hNzE2LTQ1MWI4N2M5NTk4ZSIsImFwaVRva2VuUGVwcGVyIjpudWxsLCJ2ZXJzaW9uIjozLCJpYXQiOjE3NTg0MjE3MTIsImV4cCI6MTkxNjIwOTcxMn0.OPymmbc12FXFfEGYOiYJpXjES97_m8O5fnUV4MXLabA"

X666_BASE    = "https://x666.me/v1"
X666_KEY     = "sk-WeCajmmj0VnLBAo67rFxyydr2F4UEf98RRZ31TxD2daEw4xP"

# ── Free models (Kilo.ai free tier) ──────────────────────────────────────────
FREE_MODELS = [
    "stepfun/step-3.7-flash:free",          # Best free — fast
    "openrouter/owl-alpha",                  # Good fallback
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "kilo-auto/free",
]

# ── Premium models (x666.me) ──────────────────────────────────────────────────
PREMIUM_MODELS = [
    "grok-4.3-high",           # Best quality
    "grok-4.20-fast",          # Fast
    "gpt-5.5-nx",              # GPT-5.5
    "grok-4.3-console",
    "grok-4.20-multi-agent-xhigh",
    "grok-build-console",
]

# ── Runtime config (owner can change via /setmodel) ──────────────────────────
_config = {
    "free_model":    FREE_MODELS[0],
    "premium_model": PREMIUM_MODELS[0],
}

def get_current_models():
    return dict(_config)

def set_model(tier: str, model: str):
    if tier in ("free", "premium"):
        _config[f"{tier}_model"] = model

# ── Call AI ───────────────────────────────────────────────────────────────────

async def call_ai(messages: list, is_premium: bool = False,
                  max_tokens: int = 300, temperature: float = 0.9) -> str:
    """
    Route to correct provider based on user tier.
    Auto-fallback: if premium model fails, try free model.
    """
    if is_premium:
        # Try x666.me premium
        result = await _call_x666(messages, _config["premium_model"], max_tokens, temperature)
        if result:
            return result
        # Fallback to free
    # Free tier: Kilo.ai
    result = await _call_kilo(messages, _config["free_model"], max_tokens, temperature)
    if result:
        return result
    # Last resort fallback
    for model in FREE_MODELS[1:]:
        result = await _call_kilo(messages, model, max_tokens, temperature)
        if result:
            return result
    raise Exception("All AI providers failed")


async def _call_kilo(messages: list, model: str, max_tokens: int, temperature: float):
    """Call Kilo.ai (free models for normal users)."""
    headers = {
        "Authorization": f"Bearer {KILO_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                KILO_BASE + "chat/completions",
                json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=25)
            ) as r:
                if r.status == 200:
                    d = await r.json()
                    content = d["choices"][0]["message"]["content"]
                    return content.strip() if content else None
                return None
    except Exception:
        return None


async def _call_x666(messages: list, model: str, max_tokens: int, temperature: float):
    """Call x666.me (premium models for premium users) — streaming."""
    headers = {
        "Authorization": f"Bearer {X666_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                X666_BASE + "/chat/completions",
                json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as r:
                if r.status != 200:
                    return None
                answer = ""
                async for line in r.content:
                    line = line.decode("utf-8").strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        if obj.get("choices"):
                            delta = obj["choices"][0].get("delta", {})
                            answer += delta.get("content", "") or ""
                    except Exception:
                        pass
                return answer.strip() if answer.strip() else None
    except Exception:
        return None


# ── Owner model management ─────────────────────────────────────────────────────

async def save_model_config_db():
    """Save current model config to DB so it persists restarts."""
    await get_db().bot_config.update_one(
        {"_id": "ai_models"},
        {"$set": _config},
        upsert=True
    )

async def load_model_config_db():
    """Load model config from DB on startup."""
    doc = await get_db().bot_config.find_one({"_id": "ai_models"})
    if doc:
        _config["free_model"]    = doc.get("free_model",    FREE_MODELS[0])
        _config["premium_model"] = doc.get("premium_model", PREMIUM_MODELS[0])


def get_all_models():
    return {"free": FREE_MODELS, "premium": PREMIUM_MODELS}
